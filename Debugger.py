import os, sys, traceback, gzip, re
from Components import ARMCPU, Disassembler, FunctionFlow

from Components.ARMCPU import mem_read, mem_write
from Components.Disassembler import disasm
from Components.Assembler import assemble
from Components.FunctionFlow import generateFuncList

VERSION_INFO = "Last Updated March 3rd, 2020"
print(f"VERSION INFO: {VERSION_INFO}")


# Initialization #

ROMPATH = sys.argv[1] if len(sys.argv) > 1 else None
STATEPATH = sys.argv[2] if len(sys.argv) > 2 else None
Commandque = []
with open(r"Settings.txt") as f: 
    Settings = list(f)
    InitCommandsLineNum = Settings.index("InitialCommands:\n")
    exec("".join(Settings[:InitCommandsLineNum]))
    Commandque.extend(reversed(Settings[InitCommandsLineNum+2:]))


RAM = bytearray(740322); ARMCPU.RAM = RAM; Disassembler.RAM = RAM
ROM = bytearray(); ARMCPU.ROM = ROM; Disassembler.ROM = ROM; FunctionFlow.ROM = ROM
REG = REG_INIT.copy(); ARMCPU.REG = REG
RegionMarkers = {
    2:(0x85df,0x48400),     # WRAM
    3:(0x1df,0x8000),       # IRAM
    4:(0x8ebe7,0x8ee08),    # I/O
    5:(0x81df,0x8400),      # PALETTE
    6:(0x485df,0x60400),    # VRAM
    7:(0x685df,0x68800)     # OAM
}
ARMCPU.RegionMarkers = RegionMarkers
Disassembler.RegionMarkers = RegionMarkers

OutputHandle = None
OutputCondition = False
TerminalHandle = None

UserVars = {}
UserFuncs = {}
LocalSaves = {}

Matchfunc = re.compile(r"(\w*)\(\)")  # user and global functions
Matchassign = re.compile(r"(?<![!=<>])(?:\+|-|\*|/|//|<<|>>|\*\*)?=")  # assignment of values
Matchargs = re.compile(r"([^ :(]+)[ :]*(.*)")  # grabs the debugger command and its arguments


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


def reset():
    """Clears the RAM and resets the Registers"""

    RAM[:] = bytearray(740322)
    REG[:] = REG_INIT
    UpdateGlobalInfo()


def reset_breakpoints():
    """Clears all breakpoints"""

    global BreakPoints, WatchPoints, ReadPoints, Conditionals
    BreakPoints = set(); ARMCPU.BreakPoints = BreakPoints
    WatchPoints = set(); ARMCPU.WatchPoints = WatchPoints
    ReadPoints = set(); ARMCPU.ReadPoints = ReadPoints
    Conditionals = []; ARMCPU.Conditionals = Conditionals


def importrom(filepath):
    reset()
    with open(filepath,"rb") as f:
        ROM[:] = bytearray(f.read())
    UpdateGlobalInfo()


def importstate(filepath):
    with gzip.open(filepath,"rb") as f:
        RAM[:] = bytearray(f.read())
    for i in range(17):
        REG[i] = int.from_bytes(RAM[24+4*i:28+4*i],"little")
    UpdateGlobalInfo()


reset()
reset_breakpoints()
if ROMPATH: importrom(ROMPATH)
if STATEPATH: importstate(STATEPATH)


helptext = """

    [...]  Required arguments;  (...)  Optional arguments

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

    tree [addr] (depth)             prints a tree of functions based on what functions are called in Thumb mode

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
    format [formatstr]              set the format of data sent to the output file (more details in the ReadMe)
                                        Interpolate expressions by enclosing them in curly braces
                                        presets: line / block / linexl / blockxl
    cls                             clear the console
    ?/help                          print the help text
    quit/exit                       exit the program

    @/asm                           switch to Assembly Mode
                                        In this mode, you may type in Thumb code. The code is immediately executed.
                                        If the code is not recognized, it will attempt to execute it in Debug Mode
    $/exec                          switch to Execution Mode
                                        In this mode, you may type in valid Python code to execute.
    >/debug                         switch to Debug Mode (the default mode)


    Any arguments may be replaced with User Expressions. Expressions may include any user defined variables,
    and/or "sp","lr","pc", "r0-r16", "m(addr,size)", and/or any mathematical operations between them.
    If the command takes multiple arguments, the expression must not contain spaces.

    If you ever get stuck in an infinite loop, press ctrl + C to escape it.
"""


def disT(addr,count=1):
    """Displays *count* instructions in Thumb mode starting from *addr*"""

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
    """Displays *count* instructions in Arm mode starting from *addr*"""

    for i in range(count):
        instr = mem_read(addr,4)
        print(f"{addr:0>8x}: {instr:0>8x}   {disasm(instr,0,addr+8)}")
        addr += 4


def rlist_to_int(string):
    """Takes an rlist string as input, and outputs a corresponding integer"""

    rlist = 0
    string = re.sub("r|R", "", string)
    for m in re.finditer("[^,]+", string):
        args = m.group(0).split("-")
        if len(args) == 1: lo,hi = args*2
        else: lo,hi = args
        rlist |= 2**(int(hi) + 1) - 2**int(lo)
    return rlist


def cpsr_str(cpsr):
    """Takes a 32-bit register as input, and outputs a string based on the NZCV and T flags"""

    out = ["N","Z","C","V","T"]
    for i in range(4): 
        if not cpsr & 2**(31-i): out[i] = "-"
    if not cpsr & 32: out[4] = "-"
    return "[" + "".join(out) + "]"


def hexdump(addr,count=1,size=4):
    """Displays *count* elements of *size* bytes starting from *addr*"""

    hexdata = f"{addr:0>8X}: "
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
            hexdata, strdata = f"{addr:0>8X}: ", ""
    if strdata: print(f"{hexdata.ljust(maxwidth)}  {strdata}")


def showreg():
    """Displays the registers"""

    s = ""
    for i in range(16):
        s += f"R{i:0>2}: {REG[i]:0>8X} "
        if i & 3 == 3: s += "\n"
    print(f"{s}CPSR: {cpsr_str(REG[16])}  {REG[16]:0>8X}")


def expstr(string):
    """Converts a user string into a string that can be called with eval()"""

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
    """Evaluates a user string"""

    if type(arg) is not str: return arg
    else: return eval(expstr(arg))


def formatstr(expstring):
    """Converts a user format string into an array *A* such that A[0].format(A[1:]) produces the intended string"""

    if expstring in FormatPresets: expstring = FormatPresets[expstring]
    out = [""]
    def subs(m):
        m = m.group(1).split(":")
        form = ":" + m[1] if len(m) > 1 else ""
        if re.search(r"\br\d+", m[0]):  # handles rlists
            rlist = rlist_to_int(m[0])
            separator = m[1] if len(m) > 1 else "  "
            form = m[2] if len(m) > 2 else "0>8X"
            exp = [f"R{i:0>2}: {{REG[{i}]:{form}}}" for i in range(int.bit_length(rlist)) if rlist & 2**i]
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


def assign(command, matchr=re.compile(r"r(\d+)$"), matchm=re.compile(r"m\(([^,]+),?(.+)?\)$")):
    """Assigns a value to a user variable"""

    op = Matchassign.search(command).group(0)
    identifier,expression = command.split(op)
    identifier = identifier.strip()
    try: expression = expeval(expression.strip())  # If expeval causes a syntax error, use regular eval
    except SyntaxError: expression = eval(expression)
    try: identifier = {"sp":"r13", "lr":"r14", "pc":"r15"}[identifier]
    except KeyError: pass
    regmatch = matchr.match(identifier)
    memmatch = matchm.match(identifier)
    if regmatch:
        exec(f"REG[{regmatch.group(1)}]{op}{expression}")
    elif memmatch:
        arg0,arg1 = map(expeval, memmatch.groups())
        if arg1 is None: arg1 = 4
        if op == "=": mem_write(arg0, expression, arg1)
        else: mem_write(arg0, eval(f"{mem_read(arg0,arg1)}{op[:-1]}{expression}"), arg1)
    else:
        if "[" in identifier:
            identifier = re.sub(r"\[(.*?)\]", lambda x: f"[{expstr(x.group(1))}]", identifier)
        identifier = re.sub(r"^([^ \[]*)", r"UserVars['\1']", identifier)
        exec(f"{identifier}{op}{expression}")


# Console Commands

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
    if args[0] == "all": reset_breakpoints(); print("Deleted all breakpoints")
    else: BreakPoints.remove(expeval("".join(args)))
def com_dw(*args): WatchPoints.remove(expeval("".join(args)))
def com_dr(*args): ReadPoints.remove(expeval("".join(args)))
def com_dc(*args): Conditionals.pop(expeval("".join(args)))
def com_i():
    showreg()
    print(f"Next: {ADDR:0>8X}: {INSTR:0>{2*SIZE}X}  {disasm(INSTR, MODE, PCNT)}")
def com_dist(addr,count=1): disT(expeval(addr), expeval(count))
def com_disa(addr,count=1): disA(expeval(addr), expeval(count))
def com_m(addr,count=1,size=4): hexdump(expeval(addr),expeval(count),expeval(size))
def com_if(command):
    condition, command = re.match(r"(.+?)\s*:\s*(.+)", command).groups()
    if expeval(condition): Commandque.append(command)
def com_while(command):
    condition, command = re.match(r"(.+?)\s*:\s*(.+)", command).groups()
    Commandque.append((condition, command))
def com_repeat(command):
    count, args = re.match(r"(\w+?)\s*:\s*(.+)", command).groups()
    Commandque.extend([args, expeval(count)])
def com_def(defstring):
    name, args = re.match(r"def\s+(.+?)\s*:\s*(.+)", defstring).groups()
    UserFuncs[name] = [s.strip() for s in args.split(";")]
def com_tree(address, depth=0): generateFuncList(expeval(address), expeval(depth))
def com_save(identifier="PRIORSTATE"): 
    LocalSaves[identifier] = RAM.copy(), REG.copy()
    print(f"Saved to {identifier}")
def com_load(identifier="PRIORSTATE"): 
    RAM[:] = LocalSaves[identifier][0].copy()
    REG[:] = LocalSaves[identifier][1].copy()
    UpdateGlobalInfo()
    print(f"Loaded {identifier}")
def com_dv(identifier): del UserVars[identifier]
def com_df(identifier): del UserFuncs[identifier]
def com_ds(identifier="PRIORSTATE"): del LocalSaves[identifier]
def com_vars(): print(UserVars)
def com_funcs():
    out = []
    for k,v in UserFuncs.items(): out.append(f"'{k}': {'; '.join(v)}")
    print("{" + "\n ".join(out) + "}")
def com_saves(): print(list(LocalSaves))
def com_importrom(filepath): 
    global ROMPATH
    ROMPATH = filepath.strip('"')
    importrom(ROMPATH)
    print("ROM loaded successfully")
def com_importstate(filepath): 
    global STATEPATH
    STATEPATH = filepath.strip('"')
    importstate(STATEPATH)
    print("State loaded successfully")
def com_exportstate(filepath=''):
    if filepath == '': filepath = STATEPATH
    for i in range(17): RAM[24+4*i : 28+4*i] = int.to_bytes(REG[i], 4, "little")
    with gzip.open(filepath,"wb") as f: f.write(RAM)
    print("State saved successfully")
def com_output(condition):
    global OutputHandle, OutputCondition, TerminalHandle, print
    if condition.lower() in {"close", "false", "none"}: 
        OutputCondition = False
        if OutputHandle: OutputHandle.close()
        print("Outputfile closed")
    elif condition == "clear": open(OUTPUTFILE,"w").close(); OutputHandle.seek(0)
    elif condition == "terminal":
        if not TerminalHandle:
            print("Terminal bound to " + TERMINALFILE)
            TerminalHandle = open(TERMINALFILE, "w")
            def print(*args, printinit = print, **keywords):
                printinit(*args, **keywords)
                TerminalHandle.write(" ".join(args) + "\n")
            FunctionFlow.print = print
        else: 
            TerminalHandle = None
            del print, FunctionFlow.print
            print("Terminal unbound from " + TERMINALFILE)
    else:
        if not OutputHandle: 
            OutputHandle = open(OUTPUTFILE,"w+")
        elif OutputHandle.closed:
            try: OutputHandle = open(OUTPUTFILE,"r+"); OutputHandle.seek(0,2)
            except FileNotFoundError: OutputHandle = open(OUTPUTFILE,"w+")
        if condition.lower() in {"", "true"}: OutputCondition = True
        else: OutputCondition = condition
        print("Outputting to " + OUTPUTFILE)
def com_format(command): 
    global OutputFormat
    OutputFormat = formatstr(re.match(r"format\s*:?\s*(.*)", command).group(1))
def com_cls(): os.system("cls")
def com_help(): print(helptext[1:-1])
def com_quit(): sys.exit()


commands = {
    "n":com_n, "c":com_c, "b":com_b, "bw":com_bw, "br":com_br, "bc":com_bc, "d":com_d, "dw":com_dw, "dr":com_dr, "dc":com_dc, 
    "i":com_i, "dist":com_dist, "disa":com_disa, "m":com_m, "if": com_if, "while":com_while, "rep":com_repeat, "repeat":com_repeat, 
    "def":com_def, "tree": com_tree, "save":com_save, "load":com_load, "dv":com_dv, "df":com_df, "ds":com_ds, "vars":com_vars, 
    "funcs":com_funcs, "saves":com_saves, "importrom":com_importrom, "importstate":com_importstate, "exportstate":com_exportstate, 
    "reset":reset, "output":com_output, "format":com_format, "cls":com_cls, "help":com_help, "?":com_help, "quit":com_quit, 
    "exit":com_quit}


Show = True
Pause = True
PauseCount = 0
CPUCOUNT = 0
SETINSTR = None
lastcommand = ">"
Modelist = {"@":"@", "asm":"@", "$":"$", "exec":"$", ">":">", "debug":">"}
ProgramMode = ">"
OutputFormat = formatstr(DefaultFormat)

comtype1 = {"def", "format"}  # functions that use the entire command
comtype2 = {"if", "while", "rep", "repeat", "importrom", "importstate", "exportstate", "output"}  # functions that only use the args

UpdateCheck = None


# Main Loop

while True:
    try:
        # User Input
        while Pause:
            if Commandque: 
                command = Commandque.pop()
            else:
                if OutputCondition: OutputHandle.flush()
                if TerminalHandle: TerminalHandle.write(ProgramMode + " "); TerminalHandle.flush()
                command = input(ProgramMode + " ")
                if TerminalHandle: TerminalHandle.write(command + "\n")
            if type(command) is int:  # handles repeat loops
                if command > 0: Commandque.append(command-1); command = Commandque[-2]
                else: Commandque.pop(); continue
            elif type(command) is tuple:  # handles while loops
                if expeval(command[0]): Commandque.append(command); command = command[1]
                else: continue
            command = command.strip()
            if REG[15:16] != UpdateCheck: UpdateGlobalInfo(); UpdateCheck = REG[15:16]  # Only updates if r15 or r16 have changed
            if command == "": command = lastcommand
            else: lastcommand = command
            if command in Modelist: ProgramMode = Modelist[command]; continue
            if ProgramMode == "@":
                try: 
                    SETINSTR = assemble(command, REG[15] + 2*MODE)
                    Show = ShowRegistersInAsmMode
                    break
                except (KeyError, ValueError, IndexError): pass  # treat it like a normal command
            elif ProgramMode == "$":
                try: print(eval(command))
                except SyntaxError: exec(command)
                continue
            name, args = Matchargs.match(command).groups()
            if name in comtype1: commands[name](command)
            elif ";" in command: Commandque.extend(reversed(command.split(";")))
            elif name in comtype2: commands[name](args)
            elif "\\" in command: Commandque.extend(reversed(command.split("\\")))
            elif Matchfunc.match(command):
                if name in UserFuncs: Commandque.extend(reversed(UserFuncs[name]))
                else: print(expeval(command))
            elif Matchassign.search(command): assign(command)
            elif name in commands:
                if args: commands[name](*args.split(" "))
                else: commands[name]()
            else: print(expeval(command))

        # Execute next instruction
        if SETINSTR is not None:
            MODE, SIZE, PCNT, INSTR = 1, 2, REG[15] + 2*MODE, SETINSTR
            ARMCPU.execute(SETINSTR, 1)
            if not (REG[16] & 1<<5) and REG[15] & 2: REG[15] -= 2  # if resultant mode is ARM and pc is misaligned, align it
            SETINSTR = None
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
    
    except SystemExit: sys.exit()
    except: 
        print(traceback.format_exc(), end="")
        Pause = True