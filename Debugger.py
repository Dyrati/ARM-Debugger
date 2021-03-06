import os, sys, traceback, gzip, re, math
from Components import ARMCPU, Disassembler, FunctionFlow

from Components.ARMCPU import mem_read, mem_write
from Components.Disassembler import disasm
from Components.Assembler import assemble
from Components.FunctionFlow import generateFuncList, functionBounds

VERSION_INFO = "Last Updated November 17th, 2020"
print(f"VERSION INFO: {VERSION_INFO}")


# Default Settings #

ROMPATH = sys.argv[1] if len(sys.argv) > 1 else None
STATEPATH = sys.argv[2] if len(sys.argv) > 2 else None
OUTPUTFILE = r"Debugger_Output.txt"
TERMINALFILE = r"Debugger_Terminal.txt"
ROMDIRECTORY = r""
SAVEDIRECTORY = r""

FileLimit = 10*2**20
ShowRegistersInAsmMode = True

REG_INIT = [0]*15 + [0x08000004, 0]

FormatPresets = {
    'line': r'{addr}: {instr}  {asm:20}  {cpsr}  {r0-r15}',
    'block': r'{addr}: {instr}  {asm}\n  {r0-r3}\n  {r4-r7}\n  {r8-r11}\n  {r12-r15}\n  {cpsr} {REG[16]:0>8X}\n',
    'linexl': r'{addr}:,{instr},"{asm:20}",{cpsr},{r0-r15:,}',
    'blockxl': r'{addr}:,{instr},"{asm}"\n,{r0-r3:,}\n,{r4-r7:,}\n,{r8-r11:,}\n,{r12-r15:,}\n,{cpsr},{REG[16]:0>8X}\n'
}

DefaultFormat = "line"


# Initialization #

BIOS = bytearray(0x4000); ARMCPU.BIOS = BIOS; Disassembler.BIOS = BIOS
RAM = bytearray(740322); ARMCPU.RAM = RAM; Disassembler.RAM = RAM; FunctionFlow.RAM = RAM
ROM = bytearray(); ARMCPU.ROM = ROM; Disassembler.ROM = ROM; FunctionFlow.ROM = ROM
REG = REG_INIT.copy(); ARMCPU.REG = REG
RegionMarkers = {  # Base, Length pairs
    2:(0x85df,0x48400),     # WRAM
    3:(0x1df,0x8000),       # IRAM
    4:(0x8ebe7,0x8ee08),    # I/O
    5:(0x81df,0x8400),      # PALETTE
    6:(0x485df,0x60400),    # VRAM
    7:(0x685df,0x68800)     # OAM
}
ARMCPU.RegionMarkers = RegionMarkers
FunctionFlow.RegionMarkers = RegionMarkers
Disassembler.RegionMarkers = RegionMarkers

OutputHandle = None
OutputCondition = False
TerminalHandle = None
TerminalState = False

Commandque = []
UserVars = {}
UserFuncs = {}
LocalSaves = {}

# Load data from settings file
try:
    with open(r"Debugger_Settings.txt") as f:
        Settings = f.read()
        Setting_Sections = re.search(r"Directories:\s*(.*?)Global\sVars:\s*(.*?)Initial\sCommands:\s*\n(.*)", Settings, re.S).groups()
        i = 0
        for line in Setting_Sections[0].split("\n"):
            if line:
                identifier, filepath = re.search(r"(.*?)\s*=\s*\"?(.*?)\"?\s*$", line).groups()
                if i >= 2:
                    if os.path.isdir(filepath): globals()[identifier] = filepath
                    elif filepath: print(f"DirectoryNotFound: \"{filepath}\"")
                else: globals()[identifier] = filepath
                i += 1
        exec(Setting_Sections[1])
        for line in reversed(Setting_Sections[2].split("\n")[1:]):
            if line: Commandque.append(line)
except FileNotFoundError as e: print(type(e).__name__ + ": Debugger_Settings.txt")
except AttributeError as e: print(type(e).__name__ + ": Error parsing Debugger_Settings.txt")
except Exception as e: print(type(e).__name__ + ":", e, "in Debugger_Settings.txt")


Matchfunc = re.compile(r"(\w*)\(\)")  # user and global functions; matching args in parentheses breaks m(...) command
Matchassign = re.compile(r"(?<![!=<>])(?:\+|-|\*|/|//|%|<<|>>|\*\*|&|\||\^)?=(?!=)")  # match assigment operators
Matchargs = re.compile(r"([^ :(]+)\s*:?(.*)")  # grabs the debugger command and its arguments
Matchquotes = re.compile(r"(.*?)((?:[brf]?(?:\'.*?\'|\".*?\"))|$)")  # returns (non-string, string) pairs


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
    if MODE and INSTR & 0xF800 == 0xF000: INSTR = mem_read(ADDR,4); SIZE = 4


def reset():
    """Clears the RAM and resets the Registers"""

    BIOS[:] = bytearray(0x4000)
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
    defaultpath = ROMDIRECTORY + "\\" + filepath
    if os.path.isfile(defaultpath): filepath = defaultpath
    with open(filepath,"rb") as f:
        ROM[:] = bytearray(f.read())
    UpdateGlobalInfo()


def importstate(filepath):
    defaultpath = SAVEDIRECTORY + "\\" + filepath
    if os.path.isfile(defaultpath): filepath = defaultpath
    with gzip.open(filepath,"rb") as f:
        RAM[:] = bytearray(f.read())
    for i in range(17):
        REG[i] = int.from_bytes(RAM[24+4*i:28+4*i],"little")
    UpdateGlobalInfo()


reset()
reset_breakpoints()
if ROMPATH: importrom(ROMPATH)
if STATEPATH: importstate(STATEPATH)


def print(*args, printinit=print, sep=" ", end="\n", file=sys.stdout, flush=False):
    """Enables printing to stdout and Terminal file simultaneously"""

    if TerminalState: TerminalHandle.write(sep.join(args) + end)
    printinit(*args, sep=sep, end=end, file=file, flush=flush)

FunctionFlow.print = print


def input(prompt, inputinit=input):
    """Can print inputs to Terminal file"""

    contents = inputinit(prompt)
    if TerminalState: TerminalHandle.write(prompt + contents + "\n")
    return contents



helptext = """

    [...]  Required arguments;  (...)  Optional arguments

    Commands                        Effect
                                    (nothing) repeat the previous command
    n (count)                       execute the next instruction(s), displaying the registers
    c (addr)                        continue execution up to *addr* (if addr is omitted, continues indefinitely)
    nn (count)                      execute the next instruction(s), not stepping into bl instructions
    b [addr]                        set breakpoint (if addr is "all", prints all break/watch/read points)
    bw [addr]                       set watchpoint (stops execution when *addr* is written to)
    br [addr]                       set readpoint (stops execution when *addr* is read)
    bc [condition]                  set conditional breakpoint; conditions may be any expression
    d [addr]                        delete breakpoint (if addr is "all", deletes all break/watch/read points)
    dw [addr]                       delete watchpoint
    dr [addr]                       delete readpoint
    dc [index]                      delete conditional breakpoint by index number
    i                               print the registers
    dist [addr] (count)             display *count* instructions starting from addr in THUMB
    disa [addr] (count)             display *count* instructions starting from addr in ARM
    m [addr] (bytecount) (size)     display the memory at addr (bytecount=1, size=1 by default)
    asm (addr): (command)           assemble a command written in Thumb.  If *addr* is included, you can utilize 
                                        absolute address references, like "bl $08014878", or "ldr r0, [$08014894]"
                                        if *command* is omitted, it enters multiline mode
    disasm [code]                   disassembles 16-bit machine code into Thumb
    fbounds [addr] (show)           detects and displays the boundaries of the function containing *addr*
                                        if *show* is anything, will print the function as well

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

    search [data] (size)            searches all memory for *data*, which may be a number, or byte-object
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
    exportrom (filepath)            save the current ROM to a file; filepath = (most recent import) by default
                                        will overwrite the destination, back up your saves!                                    
    reset                           reset the emulator (clears the RAM and resets registers)
    output [condition]              when *condition* is True, outputs to "Debugger_Output.txt" every CPU instruction
                                        if *condition* is "clear", deletes all the data in "Debugger_Output.txt"
    terminal (command)              can bind the terminal to "Debugger_Settings.txt"
                                        *command* may be true/false; if omitted, the bound status is toggled
                                        if *command* is "clear", clears the terminal
    format [formatstr]              set the format of data sent to the output file (more details in the ReadMe)
                                        Interpolate expressions by enclosing them in curly braces
                                        presets: line / block / linexl / blockxl

    cls                             clear the console
    dir (path)                      print all files/folders in the directory specified by *path*
    getcwd                          print the path to the current directory
    chdir [path]                    change the current directory
    ?/help                          print the help text
    quit/exit                       exit the program

    @                               switch to Assembly Mode
                                        In this mode, you may type in Thumb code. The code is immediately executed.
                                        If the code is not recognized, it will attempt to execute it in Debug Mode
    $                               switch to Execution Mode
                                        In this mode, you may type in valid Python code to execute.
    >                               switch to Debug Mode (the default mode)


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
        print(f"{init:0>8X}: {sinstr}  {disasm(instr,1,init+4)}")
        addr += 2


def disA(addr,count=1):
    """Displays *count* instructions in Arm mode starting from *addr*"""

    for i in range(count):
        instr = mem_read(addr,4)
        print(f"{addr:0>8X}: {instr:0>8x}   {disasm(instr,0,addr+8)}")
        addr += 4


def rlist_to_int(string):
    """Takes an rlist string as input, and outputs a corresponding integer"""

    rlist = 0
    string = re.sub(r"r|R", "", string)
    for m in re.finditer(r"[^,]+", string):
        args = m.group().split("-")
        if len(args) == 1: lo,hi = args*2
        else: lo,hi = args
        rlist |= 2**(int(hi) + 1) - 2**int(lo)
    return rlist


def tobytes(data, size=None): 
    if type(data) is int: 
        if size == None: size = math.ceil(int.bit_length(data)/8)
        return int.to_bytes(data, size, "little")
    elif type(data) is str: return data.encode()
    else: return bytes(data)


def cpsr_str(cpsr):
    """Takes a 32-bit register as input, and outputs a string based on the NZCV and T flags"""

    out = ["N","Z","C","V","T"]
    for i in range(4): 
        if not cpsr & 2**(31-i): out[i] = "-"
    if not cpsr & 32: out[4] = "-"
    return "[" + "".join(out) + "]"


def hexdump(addr,count=1,size=1):
    """Displays *count* bytes starting from *addr*, grouped by *size*"""

    hexdata = f"{addr:0>8X}: "
    strdata = ""
    maxwidth = 0
    offset = 0
    for i in range(count//size + (1 if count % size else 0)):
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


def search(data, size=None):
    data = tobytes(data, size)
    i = 0
    for mem in (BIOS, RAM, ROM):
        try: pos = mem.index(data); return pos, i
        except ValueError: i += 1
    return -1, i


expstr_compile = (
    (
        (re.compile(r"\$"), r"0x"),
        (re.compile(r"#"), r""),
        (re.compile(r"\br(\d+)"), r"REG[\1]"),
        (re.compile(r"\bm\((.*?)\)"), r"mem_read(\1)"),
        (re.compile(r"\b[a-zA-Z]\w*(?!\'|\")"), lambda m: expstr_compile[2](m.group(), expstr_compile[1])),
    ),
    {"sp":"REG[13]", "lr":"REG[14]", "pc":"REG[15]"},
    lambda m, reps: repr(UserVars[m]) if m in UserVars else reps[m] if m in reps else m,
)

def expstr(string):
    """Converts a user string into a string that can be called with eval()"""

    def subs(matchobj):
        s1, s2 = matchobj.groups()
        if s1:
            for k,v in expstr_compile[0]: s1 = k.sub(v,s1)
            return s1 + (s2 or "")
        else: return s2 or ""

    return Matchquotes.sub(subs, string)


def expeval(arg):
    """Evaluates a user string"""

    if type(arg) is not str: return arg
    else: return eval(expstr(arg))


def extract_args(command):
    """Extracts arguments from commands and returns an iterator"""
    
    for s1, s2 in Matchquotes.findall(command)[:-1]:
        for arg in re.findall(r"\S+", s1):
            for k,v in expstr_compile[0]: arg = k.sub(v,arg)
            yield arg
        if s2: yield s2


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


assign_compile = (
    {"sp":"r13", "lr":"r14", "pc":"r15"},
    re.compile(r"r(\d+)$"),
    re.compile(r"m\(([^,]+),?(.+)?\)$"),
    re.compile(r"\[(.*?)\]"),
    re.compile(r"^([^ \[]*)"),
)

def assign(command, matchr=re.compile(r"r(\d+)$"), matchm=re.compile(r"m\(([^,]+),?(.+)?\)$")):
    """Assigns a value to a user variable"""

    global assign_compile
    regnames, matchr, matchm, matchb, matchi = assign_compile
    op = Matchassign.search(command).group()
    identifier,expression = re.match(f"(.*?)\{op}(.*)", command).groups()
    identifier = identifier.strip()
    expression = expstr(expression.strip())
    try: identifier = regnames[identifier]
    except KeyError: pass
    regmatch = matchr.match(identifier)
    memmatch = matchm.match(identifier)
    if regmatch:
        exec(f"REG[{regmatch.group(1)}]{op}{expression}")
    elif memmatch:
        arg0,arg1 = map(expeval, memmatch.groups())
        if arg1 is None: arg1 = 4
        if op == "=": mem_write(arg0, eval(expression), arg1)
        else: mem_write(arg0, eval(f"{mem_read(arg0,arg1)}{op[:-1]}{expression}"), arg1)
    else:
        if "[" in identifier:
            identifier = matchb.sub(lambda x: f"[{expstr(x.group(1))}]", identifier)
        identifier = matchi.sub(r"UserVars['\1']", identifier)
        exec(f"{identifier}{op}{expression}")



# Console Commands

def getConsoleCommands():
    def com_n(count=1): 
        global Show, Pause, PauseCount
        Show, Pause, PauseCount = True, False, expeval(count)
    def com_c(addr=None):
        global Show, Pause, StopAddress
        Show, Pause, StopAddress = False, False, expeval(addr)
    def com_nn(count=1):
        global Show, Pause, PauseCount, SkipFuncs
        Show, Pause, PauseCount, SkipFuncs = True, False, expeval(count), True
    def com_b(addr):
        if addr == "all":
            print("BreakPoints: ", [f"{i:0>8X}" for i in sorted(BreakPoints)])
            print("WatchPoints: ", [f"{i:0>8X}" for i in sorted(WatchPoints)])
            print("ReadPoints:  ", [f"{i:0>8X}" for i in sorted(ReadPoints)])
            print("Conditionals:", Conditionals)
        else: BreakPoints.add(expeval(addr))
    def com_bw(addr): WatchPoints.add(expeval(addr))
    def com_br(addr): ReadPoints.add(expeval(addr))
    def com_bc(addr): Conditionals.append(expstr(addr))
    def com_d(addr):
        if addr == "all": reset_breakpoints(); print("Deleted all breakpoints")
        else: BreakPoints.remove(expeval(addr))
    def com_dw(addr): WatchPoints.remove(expeval(addr))
    def com_dr(addr): ReadPoints.remove(expeval(addr))
    def com_dc(addr): Conditionals.pop(expeval(addr))
    def com_i():
        showreg()
        print(f"Next: {ADDR:0>8X}: {INSTR:0>{2*SIZE}X}  {disasm(INSTR, MODE, PCNT)}")
    def com_dist(addr,count=1): disT(expeval(addr), expeval(count))
    def com_disa(addr,count=1): disA(expeval(addr), expeval(count))
    def com_m(command): 
        if re.match(r"\(", command): print(expeval("m" + command))
        else: hexdump(*map(expeval, command.split(" ")))
    def com_search(data, size=None):
        pos, mem = search(expeval(data), expeval(size))
        if mem == 0: print(f"{pos:0>8X}")
        elif mem == 1:
            for region, size in RegionMarkers.items():
                if size[0] <= pos < sum(size): print(f"{0x1000000*region + pos-size[0]:0>8X}"); break
        elif mem == 2: print(f"{0x08000000 + pos:0>8X}")
        else: print("No match found")
    def com_asm(command):
        args, asm_string = re.match(r"asm\s*([^:]*):\s*(.*)", command).groups()
        target = re.search(r"-(\S+)", args)
        if target: target = target.group(1); args = re.sub(f"-{target}", "", args)
        base = re.search(r"\S+", args)
        if base: base = expeval(base.group()) + 4
        if asm_string:
            hex_value = assemble(asm_string, pc=base)
            if target: UserVars[target] = int.to_bytes(hex_value, 2 if hex_value < 0xF800F000 else 4, "little")
            print(f"{hex_value:0>4X}  {disasm(hex_value, pc=base)}")
        else:
            asm_list = []
            if target: UserVars[target] = b''
            while True:
                inputstr = f"{base-4:0>8X}: " if base is not None else ""
                asm_input = input(inputstr)
                if not asm_input: break
                try: hex_value = assemble(asm_input, pc=base)
                except (KeyError, ValueError) as e: print(type(e).__name__+":", e); continue
                if target: UserVars[target] += int.to_bytes(hex_value, 2 if hex_value < 0xF800F000 else 4, "little")
                asm_list.append(f"{inputstr}{f'{hex_value:0>4X}':<8}  {disasm(hex_value, pc=base)}")
                if base is not None:
                    base += 2 if hex_value < 0xF800F000 else 4
            if inputstr: print()
            for line in asm_list: print(line)
    def com_disasm(*args): 
        args = list(map(expeval, args))
        if type(args[0]) is int: print(disasm(*args))
        else:
            pos = 0
            if len(args) == 1: args += [1]
            while pos < len(args[0]):
                size = 2 if args[1] != 0 else 4
                data = int.from_bytes(args[0][pos:pos+size], "little")
                if args[1] == 1 and 0xF000 <= data < 0xF800: size = 4; data = int.from_bytes(args[0][pos:pos+size], "little")
                print(f"{f'{data:0>4X}':<8}  {disasm(data, args[1])}")
                pos += size
    def com_fbounds(addr, show=""):
        if ROM:
            start, end, count = functionBounds(expeval(addr))
            if show: disT(start, count)
            print(f"(${start:0>8x}, ${end:0>8x}, count={count})")
        else: print("Error: No ROM loaded")
    def com_fboundsa(addr, show=""):
        if ROM:
            start, end, count = functionBounds(expeval(addr), mode=0)
            if show: disA(start, count)
            print(f"(${start:0>8x}, ${end:0>8x}, count={count})")
        else: print("Error: No ROM loaded")
    def com_if(command):
        condition, command = re.match(r"(.+?)\s*:\s*(.+)", command).groups()
        if ".." in command: command = iter(command.split(".."))
        if expeval(condition): Commandque.append(command)
    def com_while(command):
        condition, command = re.match(r"(.+?)\s*:\s*(.+)", command).groups()
        if ".." in command: command = command.split("..")
        def loop():
            while expeval(condition): yield command
        Commandque.append(loop())
    def com_repeat(command, group=None):
        count, command = re.match(r"(\w+?)\s*:\s*(.+)", command).groups()
        count = expeval(count)
        if ".." in command: command = command.split("..")
        def loop():
            for i in range(count): yield command
        Commandque.append(loop())
    def com_def(defstring):
        name, args = re.match(r"def\s+(.+?)\s*:\s*(.+)", defstring).groups()
        UserFuncs[name] = [s.strip() for s in args.split(";")]
    def com_tree(address, depth=0): 
        if ROM: generateFuncList(expeval(address), expeval(depth))
        else: print("No ROM loaded")
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
        print("State saved to " + filepath)
    def com_exportrom(filepath=''):
        if filepath == '': filepath = ROMPATH
        with open(filepath,"wb") as f: f.write(ROM)
        print("ROM saved to " + filepath)
    def com_output(condition):
        global OutputHandle, OutputCondition
        if condition.lower() in {"close", "false", "none"}: 
            OutputCondition = False
            if OutputHandle: OutputHandle.close()
            print("Outputfile closed")
        elif condition == "clear": 
            open(OUTPUTFILE,"w").close()
            if OutputHandle: OutputHandle.seek(0)
            print("Cleared data in " + OUTPUTFILE)
        else:
            if not OutputHandle: 
                OutputHandle = open(OUTPUTFILE,"w+")
            elif OutputHandle.closed:
                try: OutputHandle = open(OUTPUTFILE,"r+"); OutputHandle.seek(0,2)
                except FileNotFoundError: OutputHandle = open(OUTPUTFILE,"w+")
            if condition.lower() in {"", "true"}: OutputCondition = True
            else: OutputCondition = condition
            print("Outputting to " + OUTPUTFILE)
    def com_terminal(command="Toggle"):
        global TerminalHandle, TerminalState, print, input
        s = command.capitalize()
        state = bool(TerminalHandle and not TerminalHandle.closed)
        if s == "Toggle": s = str(not state)
        elif s == "Clear":
            print("Cleared data in " + TERMINALFILE)
            TerminalHandle.flush(); open(TERMINALFILE,"w").close()
            TerminalHandle.seek(0)
        if s == "True" and not state:
            if not TerminalHandle: TerminalHandle = open(TERMINALFILE, "w")
            elif TerminalHandle.closed:
                try: TerminalHandle = open(TERMINALFILE, "a")
                except FileNotFoundError: open(TERMINALFILE, "w")
            print("Terminal bound to " + TERMINALFILE)
            TerminalState = True
        elif s == "False" and state:
            TerminalHandle.close()
            TerminalState = False
            print("Terminal unbound from " + TERMINALFILE)
    def com_format(command): 
        global OutputFormat
        OutputFormat = formatstr(re.match(r"format\s*:?\s*(.*)", command).group(1))
    def com_cls(): os.system("cls")
    def com_dir(path):
        if not path: path = None
        for name in os.listdir(path): print(name)
    def com_getcwd(): print(os.getcwd())
    def com_chdir(path): os.chdir(path)
    def com_help(): print(helptext[1:-1])
    def com_quit(): sys.exit()

    commandlist = locals()
    commandlist = zip(map(lambda x: x[4:], commandlist.keys()), commandlist.values())  # removes the "com_"
    aliases = {"rep": com_repeat, "?": com_help, "exit": com_quit, "reset":reset}
    return dict(commandlist, **aliases)


commands = getConsoleCommands()


Show = True
Pause = True
PauseCount = 0  # the number of instructions until next pause
StopAddress = None  # address to stop at (like a breakpoint)
SkipFuncs = False  # whether to step into functions
BreakState = ""
CPUCOUNT = 0
lastcommand = ">"
Modelist = {"@", "$", ">"}
ProgramMode = ">"
OutputFormat = formatstr(DefaultFormat)

comtype1 = {"def", "format", "asm"}  # uses the entire command
comtype2 = {"if", "while", "rep", "repeat", "importrom", "importstate", "exportstate", "output", "dir", "chdir"}  # accepts line continuations
comtype3 = {"b", "bw", "br", "bc", "d", "dw", "dr", "dc", "m"}  # doesn't split args

UpdateCheck = None


# Main Loop

while True:
    try:
        # User Input
        while Pause:
            SkipFuncs = False
            if Commandque:
                try: command = next(Commandque[-1])
                except StopIteration: Commandque.pop(); continue
                except TypeError: command = Commandque.pop()
                if type(command) in (list, tuple): Commandque.append(iter(command)); continue
            else:
                if OutputCondition: OutputHandle.flush()
                if TerminalState: TerminalHandle.flush()
                command = input(ProgramMode + " ")
            command = command.strip()
            if REG[15:16] != UpdateCheck: UpdateGlobalInfo(); UpdateCheck = REG[15:16]  # Only updates if r15 or r16 have changed
            if command == "": command = lastcommand
            else: lastcommand = command
            if command in Modelist: ProgramMode = command; continue
            if ProgramMode == "@":
                try: 
                    user_instruction = assemble(command, REG[15] + 2*MODE)
                    ARMCPU.execute(user_instruction, 1)
                    UpdateGlobalInfo()
                    if ShowRegistersInAsmMode: showreg()
                    continue
                except Exception as e: 
                    if type(e) in {KeyError, ValueError, AttributeError}: # probably a normal command
                        pass  # KeyError = name not in thumbfuncs; ValueError = r0 = 1; AttributeError = $..n
                    else: print(type(e).__name__ + ":", e); continue
            elif ProgramMode == "$":
                try: 
                    temp = eval(command)
                    if temp is not None: print(temp)
                except SyntaxError: 
                    try: exec(command)
                    except Exception as e: print(type(e).__name__, ":", e) 
                continue
            name, args = Matchargs.match(command).groups()
            if name in comtype1: commands[name](command)
            elif ";" in command: Commandque.append(iter(command.split(";")))
            elif name in comtype2: commands[name](args)
            elif ".." in command: Commandque.append(iter(command.split("..")))
            elif Matchfunc.match(command):
                if name in UserFuncs: Commandque.append(iter(UserFuncs[name]))
                else: print(expeval(command))
            elif Matchassign.search(command): assign(command)
            elif name in comtype3: commands[name](args)
            elif name in commands: commands[name](*extract_args(args))
            else: print(expeval(command))

        if SkipFuncs:
            if not StopAddress and MODE == 1 and INSTR & 0xf800f000 == 0xf800f000:
                StopAddress = ADDR + 4
                Pause = False
                print(f"{ADDR:0>8X}: {INSTR:0>{2*SIZE}X}".ljust(19), disasm(INSTR, MODE, PCNT))
        if not BreakState:
            if ADDR in BreakPoints:
                BreakState = f"Hit BreakPoint: ${ADDR:0>8X}"
            for i in Conditionals:
                if eval(i): BreakState = f"Hit BreakPoint: {i}"
            if BreakState:
                print(BreakState)
                showreg()
                print(f"Next: {ADDR:0>8X}: {INSTR:0>{2*SIZE}X}  {disasm(INSTR, MODE, PCNT)}")
                Pause = True
                continue
        else:
            BreakState = ""
        if StopAddress == ADDR:
            StopAddress = None
            if PauseCount:
                PauseCount -= 1
                Pause = not PauseCount
            else:
                Pause = True
            showreg()
            print(f"Next: {ADDR:0>8X}: {INSTR:0>{2*SIZE}X}  {disasm(INSTR, MODE, PCNT)}")
            continue

        ARMCPU.execute(INSTR,MODE)
        CPUCOUNT += 1

        # Handlers
        if ARMCPU.BreakState:
            Show, Pause = True, True
            print("Hit " + ARMCPU.BreakState)
        if not StopAddress:
            if PauseCount: PauseCount -= 1; Pause = not PauseCount
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
    except: print(traceback.format_exc(), end=""); Pause = True

