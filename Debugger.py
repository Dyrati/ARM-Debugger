import os, sys, gzip, re, traceback
import ARMCPU, Disassembler
from ARMCPU import execute, mem_read, mem_write
from Disassembler import disasm


# Initialization #

ROM,SAVESTATE = sys.argv[1:] + [""]*(3-len(sys.argv))
OUTPUTFILE = "output.txt"
OutputHandle = None
OutputState = False
Format = "block"
LocalSaves = {}


def reset_memory():
    global Memory, Reg

    Memory = [
        bytearray(0x4000),      #BIOS
        bytearray(),            #Not used
        bytearray(0x40000),     #WRAM
        bytearray(0x8000),      #IRAM
        bytearray(0x400),       #I/O
        bytearray(0x400),       #PALETTE
        bytearray(0x18000),     #VRAM
        bytearray(0x400),       #OAM
        bytearray(),            #ROM
    ]

    Reg = [0]*17
    Reg[0] = 0x08000000
    Reg[1] = 0x000000EA
    Reg[13] = 0x03007f00
    Reg[15] = 0x08000004
    Reg[16] = 0x6000001F

    ARMCPU.Memory = Memory
    ARMCPU.Reg = Reg
    Disassembler.Memory = Memory


def reset_breakpoints():
    global BreakPoints, WatchPoints, ReadPoints, Conditionals
    BreakPoints = set(); ARMCPU.BreakPoints = BreakPoints
    WatchPoints = set(); ARMCPU.WatchPoints = WatchPoints
    ReadPoints = set(); ARMCPU.ReadPoints = ReadPoints
    Conditionals = []; ARMCPU.Conditionals = Conditionals
    

def importrom(filepath):
    reset_memory()
    with open(filepath,"rb") as f:
        Memory[8] = bytearray(f.read())


def importstate(filepath):
    locations = [(2,0x8400,0x48400),(3,0x0,0x8000),(4,0x8ea08,0x8ee08),(5,0x8000,0x8400),(6,0x48400,0x60400),(7,0x68400,0x68800)]
    with gzip.open(filepath,"rb") as f:
        save = bytearray(f.read())
    for region,start,end in locations:
        Memory[region] = save[start+0x1df:end+0x1df]
    for i in range(17):
        Reg[i] = int.from_bytes(save[24+4*i:28+4*i],"little")


reset_memory()
reset_breakpoints()
if ROM: importrom(ROM)
if SAVESTATE: importstate(SAVESTATE)


helptext = """
    [...]  Required arguments;  (...)  Optional arguments
    Any numerical arguments may be replaced with User Expressions. Expressions may include "sp","lr","pc", "r0-r16", 
    "m(addr,size)" (the data at addr; size=4 by default), and/or any user defined variables.

    Commands                        Effect
                                    (nothing) repeat the previous command
    n (count)                       execute the next instruction(s), displaying the registers
    c (count)                       continue execution (if count is omitted, continues forever)
    b [addr]                        set breakpoint (if addr is "all", prints all break/watch/read points)
    bw [addr]                       set watchpoint
    br [addr]                       set readpoint
    bc [expression]                 set conditional breakpoint
    d [addr]                        delete breakpoint (if addr is "all", deletes all break/watch/read points)
    dw [addr]                       delete watchpoint
    dr [addr]                       delete readpoint
    dc [index]                      delete conditional breakpoint by index
    i                               print the registers
    dist [addr] (count)             display *count* instructions starting from addr in THUMB
    disa [addr] (count)             display *count* instructions starting from addr in ARM
    m [addr] (count) (size)         display the memory at addr (count=1, size=4 by default)
    setm [addr] [value] (size)      modify *size* bytes at addr; size=4 by default
    setr [register] [value]         modify a register; set regnum to 16 to modify CPSR; accepts r0-r16 and sp/lr/pc

    [identifier] = [expression]     create a user variable
    dv [identifier]                 delete user variable
    vars                            print all user variables
    save (identifier)               create a local save; identifier = PRIORSTATE by default
    load (identifier)               load a local save; identifier = PRIORSTATE by default
    ds [identifier]                 delete local save
    saves                           print all local save identifiers
    eval [expression]               print the value of *expression*

    importrom [filepath]            import a rom into the debugger
    importstate [filepath]          import a savestate
    output [arg]                    if arg is "True", outputs to "output.txt"; if arg is "False", does not output
                                        if arg is "clear", deletes the data in "output.txt"
    format [preset]                 set the format of data sent to the output file
                                        presets: line / block / linexl / blockxl  (xl suffix for Excel formatting)
    cls                             clear the console
    h/help/?                        print the help text
    quit/exit                       exit the program
    e                               switch to Execution Mode
                                        In this mode, you may type in valid code which will be executed.
                                        Enter nothing to return to Normal Mode.
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


def expstr(string):
    reps = {"sp":"r13", "lr":"r14", "pc":"r15"}
    reps.update(UserVars)
    string = re.sub("[a-zA-Z]\w*", lambda x: reps[x.group(0)] if x.group(0) in reps else x.group(0), string)
    reps = {"\$":"0x", "#":"", r"\bx":"0x", r"r(\d+)":r"Reg[\1]", r"m\((.*)\)":r"mem_read(\1)"}
    for k,v in reps.items(): string = re.sub(k,v,string)
    return string


def expeval(args):
    try: return eval(expstr("".join(args)))
    except TypeError: return eval(expstr(args))


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
        if offset % 16 == 0:
            maxwidth = len(hexdata)
            print(f"{hexdata}  {strdata}")
            hexdata, strdata = f"{addr+offset:0>8X}:  ", ""
    if strdata: print(f"{hexdata.ljust(maxwidth)}  {strdata}")


def showreg():
    s = ""
    for i in range(16):
        s += f"R{i:0>2}: {Reg[i]:0>8X} "
        if i & 3 == 3: s += "\n"
    cpsr = "NZCVT"
    bits = (31,30,29,28,5)
    cpsr = ''.join([cpsr[i] if Reg[16] & 1<<bits[i] else "-" for i in range(5)])
    print(s + f"CPSR: [{cpsr}] {Reg[16]:0>8X}")


def writefile(preset):
    preset = preset.lower()
    cpsr = "NZCVT"
    bits = (31,30,29,28,5)
    cpsr = ''.join([cpsr[i] if Reg[16] & 1<<bits[i] else "-" for i in range(5)])
    if preset == "line":
        outstring = f"{Addr:0>8X}: {instr:0>{2*Size}X}".ljust(20) + f"{disasm(instr,Mode,RegInit[15])[:20]}".ljust(22) + f"CPSR: [{cpsr}]"
        for i in range(16): 
            outstring += f"  R{i:0>2}: {Reg[i]:0>8x}"
    elif preset == "block":
        outstring = f"{Addr:0>8X}: {instr:0>{2*Size}X}".ljust(20) + f"{disasm(instr,Mode,RegInit[15])}"
        for i in range(16):
            if i%4 == 0: outstring += "\n"
            outstring += f"  R{i:0>2}: {Reg[i]:0>8x}"
        outstring += f"\n  CPSR: [{cpsr}]  {Reg[16]:0>8X}\n"
    elif preset == "linexl":
        outstring = f"{Addr:0>8X}:\t{instr:0>{2*Size}X}\t{disasm(instr,Mode,RegInit[15])}\tCPSR: [{cpsr}]"
        for i in range(16): 
            outstring += f"\tR{i:0>2}: {Reg[i]:0>8x}"
    elif preset == "blockxl":
        outstring = f"{Addr:0>8X}:\t{instr:0>{2*Size}X}\t{disasm(instr,Mode,RegInit[15])}\t\tCPSR: [{cpsr}]"
        for i in range(16):
            if i%4 == 0: outstring += "\n"
            outstring += f"\tR{i:0>2}: {Reg[i]:0>8x}"
        outstring += "\n"
    OutputHandle.write(outstring + "\n")



Show = True
Pause = True
PauseCount = 0
UserVars = {}
lastcommand = ""
ExecMode = False


while True:

    # Interface
    while Pause:
        if OutputState: OutputHandle.flush()
        try:
            if ExecMode:
                command = input(">> ")
                if command == "": ExecMode = False
                else:
                    exec(command)
                    try: print(eval(command))
                    except SyntaxError: pass
            else:
                command = input("> ").strip()
                name,*args = command.split(" ")
                if name == "": name,*args = lastcommand.split(" ")
                else: lastcommand = command
                if len(command.split("=")) == 2:
                    identifier,expression = command.split("=")
                    UserVars[identifier.strip()] = str(eval(expstr(expression)))
                elif name == "n": 
                    Show,Pause = True,False
                    try: PauseCount = expeval(args[0])
                    except IndexError: PauseCount = 1
                elif name == "c": 
                    Show,Pause = False,False
                    try: PauseCount = expeval(args[0])
                    except IndexError: PauseCount = 0
                elif name == "b":
                    if args[0] == "all":
                        print("BreakPoints: ", [f"{i:0>8X}" for i in sorted(BreakPoints)])
                        print("WatchPoints: ", [f"{i:0>8X}" for i in sorted(WatchPoints)])
                        print("ReadPoints:  ", [f"{i:0>8X}" for i in sorted(ReadPoints)])
                        print("Conditionals:", Conditionals)
                    else: BreakPoints.add(expeval(args))
                elif name == "bw": WatchPoints.add(expeval(args))
                elif name == "br": ReadPoints.add(expeval(args))
                elif name == "bc": Conditionals.append(expstr("".join(args)))
                elif name == "d":
                    if args[0] == "all": reset_breakpoints()
                    else: BreakPoints.remove(expeval(args))
                elif name == "dw": WatchPoints.remove(expeval(args))
                elif name == "dr": ReadPoints.remove(expeval(args))
                elif name == "dc": Conditionals.pop(expeval(args))
                elif name == "i": showreg()
                elif name == "dist":
                    try: disT(expeval(args[0]), expeval(args[1]))
                    except IndexError: disT(expeval(args[0]))
                elif name == "disa":
                    try: disA(expeval(args[0]), expeval(args[1]))
                    except IndexError: disA(expeval(args[0]))
                elif name == "m": hexdump(expeval(args[0]),*(expeval(i) for i in args[1:]))
                elif name == "setm":
                    size = expeval(args[2]) if len(args) == 3 else 4
                    mem_write(expeval(args[0]), expeval(args[1]), size)
                elif name == "setr":
                    args[0] = re.sub(r"^r(\d+)$", r"\1", args[0])
                    reps = {"sp":"13","lr":"14","pc":"15"}
                    if args[0] in reps: args[0] = reps[args[0]]
                    Reg[expeval(args[0])] = expeval(args[1])
                elif name == "dv": del UserVars[args[0]]
                elif name == "vars": print(UserVars)
                elif name == "save": 
                    try: identifier = args[0]
                    except IndexError: identifier = "PRIORSTATE"
                    LocalSaves[identifier] = [], Reg.copy()
                    for i in range(8): LocalSaves[identifier][0].append(Memory[i].copy())
                elif name == "load":
                    try: identifier = args[0]
                    except IndexError: identifier = "PRIORSTATE"
                    for i in range(8): Memory[i] = LocalSaves[identifier][0][i].copy()
                    Reg = LocalSaves[identifier][1].copy()
                    ARMCPU.Reg = Reg
                elif name == "ds": del LocalSaves[args[0]]
                elif name == "saves": print(list(LocalSaves))
                elif name == "eval": print(expeval(args))
                elif name == "importrom": importrom(" ".join(args).strip('"'))
                elif name == "importstate": importstate(" ".join(args).strip('"'))
                elif name == "output":
                    arg0 = args[0].lower()
                    if arg0 == "true": 
                        if not OutputHandle: OutputHandle = open(OUTPUTFILE,"w+")
                        OutputState = True
                    elif arg0 == "false": OutputState = False
                    elif arg0 == "clear": open(OUTPUTFILE,"w").close(); OutputHandle.seek(0)
                elif name == "format": Format = args[0]
                elif name == "cls": os.system("cls")
                elif name in {"h","help","?"}: print(helptext[1:-1])
                elif name in {"quit","exit"}: quit()
                elif name == "e": lastcommand = ""; ExecMode = True
                else: print("Unrecognized command")
        except Exception:
            print(traceback.format_exc(),end="")
    else:
        if not Memory[8]: 
            print("Error: No ROM loaded")
            Pause = True
            continue

    # Find next instruction
    RegInit = Reg.copy()
    Mode = Reg[16]>>5 & 1
    Size = 4 - 2*Mode
    Addr = (Reg[15] - Size) & ~(Size-1)
    instr = mem_read(Addr,Size)
    if Mode and 0xF000 <= instr < 0xF800: instr = mem_read(Addr,4); Size = 4
    execute(instr,Mode)

    # Handlers
    BreakState = ARMCPU.BreakState
    if Addr in BreakPoints: 
        BreakState = f"BreakPoint: ${Addr:0>8X}"
    for i in Conditionals:
        if eval(i): BreakState = f"BreakPoint: {i}"
    if PauseCount: PauseCount -= 1; Pause = not PauseCount
    if BreakState:
        Show,Pause = True,True
        print("Hit " + BreakState)
        BreakState = ""
        ARMCPU.BreakState = ""
    if Show:
        print(f"{Addr:0>8X}: {instr:0>{2*Size}X}".ljust(19), disasm(instr, Mode, RegInit[15]))
        showreg()
    if OutputState:
        writefile(Format)
