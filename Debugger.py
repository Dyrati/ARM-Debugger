import os, sys, traceback, gzip, re
from Components import ARMCPU, Disassembler

from Components.ARMCPU import mem_read, mem_write
from Components.Disassembler import disasm
from Components.Assembler import assemble


# Initialization #

ROMPATH = sys.argv[1] if len(sys.argv) > 1 else None
STATEPATH = sys.argv[2] if len(sys.argv) > 2 else None
RAM = bytearray(740322); ARMCPU.RAM = RAM; Disassembler.RAM = RAM
ROM = bytearray(); ARMCPU.ROM = ROM; Disassembler.ROM = ROM
REG = [0]*17; ARMCPU.REG = REG
RegionMarkers = {
    2:(0x85df,0x48400),     # WRAM
    3:(0x1df,0x8000),       # IRAM
    4:(0x8ebe7,0x8ee08),    # I/O
    5:(0x81df,0x8400),      # PALETTE
    6:(0x485df,0x60400),    # VRAM
    7:(0x685df,0x68800)}    # OAM
ARMCPU.RegionMarkers = RegionMarkers
Disassembler.RegionMarkers = RegionMarkers
OUTPUTFILE = "output.txt"
FormatPresets = {
    "line": r"{addr}: {instr}  {asm:20}  {cpsr}  {r0-r15}",
    "block": r"{addr}: {instr}  {asm}\n  {r0-r3}\n  {r4-r7}\n  {r8-r11}\n  {r12-r15}\n  {cpsr}\n",
    "linexl": r"{addr}:\t{instr}\t{asm:20}\t{cpsr}\t{r0-r15:\t}",
    "blockxl": r"{addr}:\t{instr}\t{asm}\t\t{cpsr}\n\t{r0-r3:\t}\n\t{r4-r7:\t}\n\t{r8-r11:\t}\n\t{r12-r15:\t}\n\t{cpsr}\n"}
OutputHandle = None
OutputCondition = False
FileLimit = 10*2**20
UserVars = {}
UserFuncs = {}
LocalSaves = {}


def reset():
    RAM[:] = bytearray(740322)
    REG[:] = [0]*17
    REG[0] = 0x08000000
    REG[1] = 0x000000EA
    REG[13] = 0x03007f00
    REG[15] = 0x08000004
    REG[16] = 0x6000001F


def reset_breakpoints():
    global BreakPoints, WatchPoints, ReadPoints, Conditionals
    BreakPoints = set(); ARMCPU.BreakPoints = BreakPoints
    WatchPoints = set(); ARMCPU.WatchPoints = WatchPoints
    ReadPoints = set(); ARMCPU.ReadPoints = ReadPoints
    Conditionals = []; ARMCPU.Conditionals = Conditionals
    

def importrom(filepath):
    reset()
    with open(filepath,"rb") as f:
        ROM[:] = bytearray(f.read())


def importstate(filepath):
    with gzip.open(filepath,"rb") as f:
        RAM[:] = bytearray(f.read())
    for i in range(17):
        REG[i] = int.from_bytes(RAM[24+4*i:28+4*i],"little")


reset()
reset_breakpoints()
if ROMPATH: importrom(ROMPATH)
if STATEPATH: importstate(STATEPATH)


helptext = """
    [...]  Required arguments;  (...)  Optional arguments
    Any arguments may be replaced with User Expressions. Expressions may include any user defined variables,
    and/or "sp","lr","pc", "r0-r16", "m(addr,size)", and/or any mathematical operations between them.
    If the command takes multiple arguments, the expression must not contain spaces.

    Commands                        Effect
                                    (nothing) repeat the previous command
    n (count)                       execute the next instruction(s), displaying the registers
    c (count)                       continue execution (if count is omitted, continues indefinitely)
    b [addr]                        set breakpoint (if addr is "all", prints all break/watch/read points)
    bw [addr]                       set watchpoint
    br [addr]                       set readpoint
    bc [condition]                  set conditional breakpoint; conditions may be any expression
    d [addr]                        delete breakpoint (if addr is "all", deletes all break/watch/read points)
    dw [addr]                       delete watchpoint
    dr [addr]                       delete readpoint
    dc [index]                      delete conditional breakpoint by index number
    i                               print the registers
    dist [addr] (count)             display *count* instructions starting from addr in THUMB
    disa [addr] (count)             display *count* instructions starting from addr in ARM
    m [addr] (count) (size)         display the memory at addr (count=1, size=4 by default)


    if [condition]: [command]       execute *command* if *condition* is true
    while [condition]: [command]    repeat *command* while *condition* is true
    rep/repeat [count]: [command]   repeat *command* *count* times

    [name][op][expression]          create/modify a User Variable; *op* may be =, +=, -=, *=, etc
                                        if name is r0-r16 or sp/lr/pc, you can modify a register
                                        if name is m(addr,size), you can modify a value in memory
    def [name]: [commands]          bind a list of commands separated by semicolons to *name*
                                        commands may be ANY valid debugger commands
                                        execute these functions later by typing in "name()"
                                        you can call functions within functions, with unlimited nesting
    save (name)                     create a local save; name = PRIORSTATE by default
    load (name)                     load a local save; name = PRIORSTATE by default
    dv [name]                       delete user variable
    df [name]                       delete user function
    ds (name)                       delete local save; name = PRIORSTATE by default
    vars                            print all user variables
    funcs                           print all user functions
    saves                           print all local saves

    importrom [filepath]            import a rom into the debugger
    importstate [filepath]          import a savestate
    exportstate (filepath)          save the current state to a file; filepath = (most recent import) by default
                                        will overwrite the destination, back up your saves!
    reset                           reset the emulator (clears the RAM and resets registers)
    output [condition]              when *condition* is True, outputs to "output.txt"; (after each instruction)
                                        if *condition* is "clear", deletes all the data in "output.txt"
    format [formatstr]              set the format of data sent to the output file
                                        Interpolate expressions by enclosing them in curly braces
                                        presets: line / block / linexl / blockxl  (xl suffix for Excel formatting)
    cls                             clear the console
    ?/help                          print the help text
    quit/exit                       exit the program

    @/asm                           switch to Assembly Mode
                                        In this mode, you may type in Thumb code. The code is immediately executed.
                                        If the code is not recognized, it will attempt to execute it in Debug Mode
    $/exec                          switch to Execution Mode
                                        In this mode, you may type in valid Python code to execute.
    >/debug                         switch to Debug Mode (the default mode)
"""


def disT(addr,count=1):
    for i in range(count):
        init = addr
        instr = mem_read(init,2)
        sinstr = f"{instr:0>4x}     "
        if 0xF000 <= instr < 0xF800:
            instr = mem_read(init,4)
            addr += 2
            sinstr = f"{instr & 0xFFFF:0>4x} {instr>>16:0>4x}"
        print(f"{init:0>8x}: {sinstr}  {disasm(instr,1,init+4)}")
        addr += 2


def disA(addr,count=1):
    for i in range(count):
        instr = mem_read(addr,4)
        print(f"{addr:0>8x}: {instr:0>8x}   {disasm(instr,0,addr+8)}")
        addr += 4


def rlist_to_int(string):
    rlist = 0
    string = re.sub("r|R", "", string)
    for m in re.finditer("[^,]+", string):
        args = m.group(0).split("-")
        if len(args) == 1: lo,hi = args*2
        else: lo,hi = args
        rlist |= 2**(int(hi) + 1) - 2**int(lo)
    return rlist


def cpsr_str(cpsr):
    out = ["N","Z","C","V","T"]
    for i in range(4): 
        if not cpsr & 2**(31-i): out[i] = "-"
    if not cpsr & 32: out[4] = "-"
    return "[" + "".join(out) + "]"


def hexdump(addr,count=1,size=4):
    hexdata = f"{addr:0>8X}:  "
    strdata = ""
    maxwidth = 0
    offset = 0
    for i in range(count):
        value = mem_read(addr+offset, size)
        hexdata += f"{value:0>{2*size}X} "
        for j in range(size):
            c = value>>8*j & 0xFF
            if 32 <= c < 127: strdata += chr(c)
            else: strdata += "."
        offset += size
        if offset >= 16:
            addr += offset
            offset = 0
            maxwidth = len(hexdata)
            print(f"{hexdata}  {strdata}")
            hexdata, strdata = f"{addr:0>8X}:  ", ""
    if strdata: print(f"{hexdata.ljust(maxwidth)}  {strdata}")


def showreg():
    s = ""
    for i in range(16):
        s += f"R{i:0>2}: {REG[i]:0>8X} "
        if i & 3 == 3: s += "\n"
    print(s + cpsr_str(REG[16]))


def UpdateGlobalInfo():
    """Updates the global variables:  

    MODE - 0 if in ARM mode, 1 if in THUMB mode  
    SIZE - The number of bytes of the next instruction  
    PCNT - What the program counter will be while executing the next instruction (r15 + SIZE)  
    ADDR - The current address  
    INSTR - The next machine code instruction to be executed
    """
    global MODE, SIZE, PCNT, ADDR, INSTR
    MODE = REG[16]>>5 & 1
    SIZE = 4 - 2*MODE
    PCNT = REG[15] + SIZE
    ADDR = (REG[15] - SIZE) & ~(SIZE-1)
    INSTR = mem_read(ADDR,SIZE)
    if MODE and 0xF000 <= INSTR < 0xF800: INSTR = mem_read(ADDR,4); SIZE = 4


def expstr(string):
    reps = {"sp":"r13", "lr":"r14", "pc":"r15"}
    def subs(matchobj): 
        m = matchobj.group(0)
        if m in UserVars: return str(UserVars[m])
        elif m in reps: return reps[m]
        else: return m
    string = re.sub(r"[a-zA-Z]\w*", subs, string)
    reps = {"\$":"0x", "#":"", r"\bx(\d+)":r"0x\1", r"\br(\d+)":r"REG[\1]", r"\bm\((.*)\)":r"mem_read(\1)"}
    for k,v in reps.items(): string = re.sub(k,v,string)
    return string


def expeval(arg):
    if type(arg) is not str: return arg
    else: return eval(expstr(arg))


def formatstr(expstring):
    if expstring in FormatPresets: expstring = FormatPresets[expstring]
    out = [""]
    def subs(m):
        m = m.group(1).split(":")
        form = ":" + m[1] if len(m) > 1 else ""
        if re.search(r"\br\d+", m[0]):  # handles rlists
            rlist = rlist_to_int(m[0])
            separator = m[1] if len(m) > 1 else "  "
            form = m[2] if len(m) > 2 else "0>8X"
            exp = [f"R{i:0>2}: {{REG[{i}]:{form}}}" for i in range(16) if rlist & 2**i]
            return separator.join(exp)
        elif m[0] in {"addr", "ADDR"}: return f"{{ADDR{form if form else ':0>8X'}}}"
        elif m[0] in {"instr", "INSTR"}: return f"{{INSTR{form if form else ':0>8X'}}}"
        elif m[0] in {"asm", "ASM"}: 
            try:
                form = int(m[1])
                form1, form2 = f"[:{form}]", f":<{form}"
            except (IndexError, ValueError): 
                form1, form2 = form, form
            out.append(f"disasm(INSTR, MODE, PCNT){form1}")
            return f"{{_G[{len(out)-2}]{form2}}}"
        elif m[0] in {"cpsr", "CPSR"}:
            out.append("cpsr_str(REG[16])")
            return f"CPSR: {{_G[{len(out)-2}]{form}}}"
        else:
            out.append(expstr(m[0]))
            return f"{{_G[{len(out)-2}]{form}}}"
    out[0] = re.sub(r"{(.*?)}", subs, expstring.replace("\\n","\n").replace("\\t","\t") + "\n")
    return out


def assign(command):
    op = re.search("(=|!|>|<|\+|-|\*|//|/|&|\^|\||%|<<|>>|\*\*)?=", command)
    if op and op.group(1) not in {"=","!",">","<"}:
        op = op.group(0)
        identifier,expression = command.split(op)
        identifier = identifier.strip()
        try: expression = expeval(expression.strip())
        except SyntaxError: expression = eval(expression)
        try: identifier = {"sp":"r13", "lr":"r14", "pc":"r15"}[identifier]
        except KeyError: pass
        matchr = re.match(r"r(\d+)$",identifier)
        matchm = re.match(r"m\(([^,]+),?(.+)?\)$",identifier)
        if matchr: exec(f"REG[{int(matchr.group(1))}]{op}{expression}")
        elif matchm:
            arg0,arg1 = map(expeval, matchm.groups())
            if arg1 is None: arg1 = 4
            if op == "=": mem_write(arg0, expression, arg1)
            else: mem_write(arg0, eval(f"{mem_read(arg0,arg1)}{op[:-1]}{expression}"), arg1)
        else:
            if "[" in identifier:
                identifier = re.sub(r"\[(.*?)\]", lambda x: f"[{expstr(x.group(1))}]", identifier)
            identifier = re.sub(r"^([^ \[]*)", r"UserVars['\1']", identifier)
            exec(f"{identifier}{op}{expression}")
        return True
        

def com_n(count=1): 
    global Show, Pause, PauseCount
    Show, Pause, PauseCount = True, False, expeval(count)
def com_c(count=0):
    global Show,Pause,PauseCount
    Show,Pause,PauseCount = False, False, expeval(count)
def com_b(*args):
    if args[0] == "all":
        print("BreakPoints: ", [f"{i:0>8X}" for i in sorted(BreakPoints)])
        print("WatchPoints: ", [f"{i:0>8X}" for i in sorted(WatchPoints)])
        print("ReadPoints:  ", [f"{i:0>8X}" for i in sorted(ReadPoints)])
        print("Conditionals:", Conditionals)
    else: BreakPoints.add(expeval("".join(args)))
def com_bw(*args): WatchPoints.add(expeval("".join(args)))
def com_br(*args): ReadPoints.add(expeval("".join(args)))
def com_bc(*args): Conditionals.append(expstr("".join(args)))
def com_d(*args):
    if args[0] == "all": reset_breakpoints()
    else: BreakPoints.remove(expeval("".join(args)))
def com_dw(*args): WatchPoints.remove(expeval("".join(args)))
def com_dr(*args): ReadPoints.remove(expeval("".join(args)))
def com_dc(*args): Conditionals.pop(expeval("".join(args)))
def com_i():
    showreg()
    print(f"{ADDR:0>8X}: {INSTR:0>{2*SIZE}X}".ljust(19), disasm(INSTR, MODE, PCNT))
def com_dist(addr,count=1): disT(expeval(addr), expeval(count))
def com_disa(addr,count=1): disA(expeval(addr), expeval(count))
def com_m(addr,count=1,size=4): hexdump(expeval(addr),expeval(count),expeval(size))
def com_if(*args):
    condition, command = re.match(r"(.+?)\s*:\s*(.*)"," ".join(args)).groups()
    if expeval(condition) and command: Commandque.append(command)
def com_while(*args):
    condition, command = re.match(r"(.+?)\s*:\s*(.*)"," ".join(args)).groups()
    if command: Commandque.append((condition, command))
def com_repeat(*args):
    count, args = re.match(r"(\d+?)\s*:\s*(.*)"," ".join(args)).groups()
    if args: Commandque.extend([args, int(count)])
def com_def(defstring, depth=0):
    name, args = re.match(r"def\s+(.+?)\s*:\s*(.*)", defstring).groups()
    if not(args):
        depth += 1
        UserFuncs[name] = []
        while True:
            s = input(" "*(depth*4+2)).strip()
            if not s: break
            elif re.match(r"def", s): com_def(s, depth)
            else: UserFuncs[name].append(s)
    else: UserFuncs[name] = [s.strip() for s in args.split(";")]
def com_save(identifier="PRIORSTATE"): LocalSaves[identifier] = RAM.copy(), REG.copy()
def com_load(identifier="PRIORSTATE"): 
    RAM[:] = LocalSaves[identifier][0].copy()
    REG[:] = LocalSaves[identifier][1].copy()
def com_dv(identifier): del UserVars[identifier]
def com_df(identifier): del UserFuncs[identifier]
def com_ds(identifier="PRIORSTATE"): del LocalSaves[identifier]
def com_vars(): print(UserVars)
def com_funcs():
    out = []
    for k,v in UserFuncs.items(): out.append(f"'{k}': {'; '.join(v)}")
    print("{" + "\n ".join(out) + "}")
def com_saves(): print(list(LocalSaves))
def com_importrom(*args): 
    global ROMPATH
    ROMPATH = " ".join(args).strip('"')
    importrom(ROMPATH)
def com_importstate(*args): 
    global STATEPATH
    STATEPATH = " ".join(args).strip('"')
    importstate(STATEPATH)
def com_exportstate(filepath=None):
    if filepath is None: filepath = STATEPATH
    for i in range(17): RAM[24+4*i : 28+4*i] = int.to_bytes(REG[i], 4, "little")
    with gzip.open(filepath,"wb") as f: f.write(RAM)
def com_output(condition):
    global OutputHandle, OutputCondition
    if condition.lower() == "false": 
        OutputCondition = False
        if OutputHandle: OutputHandle.close()
    elif condition == "clear": open(OUTPUTFILE,"w").close(); OutputHandle.seek(0)
    else:
        if not OutputHandle: OutputHandle = open(OUTPUTFILE,"w+")
        elif OutputHandle.closed: OutputHandle = open(OUTPUTFILE,"r+"); OutputHandle.seek(0,2)
        if condition.lower() == "true": OutputCondition = True
        else: OutputCondition = condition
def com_format(command): 
    global OutputFormat
    OutputFormat = formatstr(re.match(r"format\s*:?\s*(.*)", command).group(1))
def com_cls(): os.system("cls")
def com_help(): print(helptext[1:-1])
def com_quit(): sys.exit()


commands = {
    "n":com_n, "c":com_c, "b":com_b, "bw":com_bw, "br":com_br, "bc":com_bc, "d":com_d, "dw":com_dw, "dr":com_dr, "dc":com_dc, 
    "i":com_i, "dist":com_dist, "disa":com_disa, "m":com_m, "if": com_if, "while":com_while, "rep":com_repeat, "repeat":com_repeat, 
    "def":com_def, "save":com_save, "load":com_load, "dv":com_dv, "df":com_df, "ds":com_ds, "vars":com_vars, "funcs":com_funcs, 
    "saves":com_saves, "importrom":com_importrom, "importstate":com_importstate, "exportstate":com_exportstate, "reset":reset, 
    "output":com_output, "format":com_format, "cls":com_cls, "help":com_help, "?":com_help, "quit":com_quit, "exit":com_quit}


Show = True
Pause = True
PauseCount = 0
CPUCOUNT = 0
lastcommand = ">"
Modelist = ["@", "asm", "$", "exec", ">", "debug"]
ProgramMode = ">"
OutputFormat = formatstr("line")
Commandque = []


while True:

    # User Input
    while Pause:
        try:
            if not Commandque and expeval(OutputCondition): OutputHandle.flush()
            command = Commandque.pop() if Commandque else input(ProgramMode + " ")
            if type(command) is int:
                if command > 0: Commandque.append(command-1); command = Commandque[-2]
                else: Commandque.pop(); continue
            elif type(command) is tuple:
                if expeval(command[0]): Commandque.append(command); command = command[1]
                else: continue
            command = command.strip()
            UpdateGlobalInfo()
            if command == "": command = lastcommand
            else: lastcommand = command
            if command in Modelist: ProgramMode = Modelist[Modelist.index(command) & ~1]; continue
            if ProgramMode == "@":
                try: SETINSTR = assemble(command, REG[15] + 2*MODE); Show = True; break
                except (KeyError, ValueError, IndexError): SETINSTR = None
            elif ProgramMode == "$":
                try: print(eval(command))
                except SyntaxError: exec(command)
                continue
            name, args = re.match(r"([^ :]+)\s*:?\s*(.*)", command).groups()
            if name in {"def", "format"}: commands[name](command); continue
            elif ";" in command: Commandque.extend(reversed(command.split(";"))); continue
            elif "\\" in command and name not in {"importrom", "importstate", "exportstate", "if", "rep", "repeat", "while"}:
                Commandque.extend(reversed(command.split("\\"))); continue
            matchfunc = re.match(r"(\w*)\s?\(.*\)", command)
            if matchfunc and matchfunc.group(1) in UserFuncs:
                Commandque.extend(reversed(UserFuncs[matchfunc.group(1)])); continue
            try: 
                if args: commands[name](*args.split(" "))
                else: commands[name]()
            except (KeyError, SyntaxError, TypeError):
                if not assign(command):
                    try: print(expeval(command))
                    except NameError: print("Unrecognized command")
        except Exception: print(traceback.format_exc(), end="")
        

    # Execute next instruction
    if ProgramMode == "@" and SETINSTR is not None:
        MODE, SIZE, PCNT, INSTR = 1, 2, REG[15] + 2*MODE, SETINSTR
        ARMCPU.execute(SETINSTR, 1)
        if not (REG[16] & 1<<5) and REG[15] & 2: REG[15] -= 2
    else:
        ARMCPU.execute(INSTR,MODE)
    CPUCOUNT += 1

    # Handlers
    BreakState = ARMCPU.BreakState
    if ADDR in BreakPoints: 
        BreakState = f"BreakPoint: ${ADDR:0>8X}"
    for i in Conditionals:
        if eval(i): BreakState = f"BreakPoint: {i}"
    if PauseCount: PauseCount -= 1; Pause = not PauseCount
    if BreakState:
        Show,Pause = True,True
        print("Hit " + BreakState)
        BreakState = ""
    if Show:
        print(f"{ADDR:0>8X}: {INSTR:0>{2*SIZE}X}".ljust(19), disasm(INSTR, MODE, PCNT))
        showreg()

    if expeval(OutputCondition):
        OutputHandle.write(OutputFormat[0].format(ADDR=ADDR, INSTR=INSTR, REG=REG, MODE=MODE, CPUCOUNT=CPUCOUNT, 
            _G=[eval(x) for x in OutputFormat[1:]]))
        if OutputHandle.tell() > FileLimit:
            order = max(0,(int.bit_length(FileLimit)-1)//10)
            message = f"Warning: output file has exceeded {FileLimit//2**(10*order)} {('','K','M','G')[order]}B"
            print(f"{'~'*len(message)}\n{message}\n{'~'*len(message)}")
            s = input("Proceed? y/n: ")
            if s.lower() in {"y","yes"}: FileLimit *= 4
            else: Pause = True

    UpdateGlobalInfo()
