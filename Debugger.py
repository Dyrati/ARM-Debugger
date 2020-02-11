import os, sys, gzip, re, traceback
import ARMCPU, Disassembler
from ARMCPU import execute, mem_read, mem_write
from Disassembler import disasm


# Initialization #

ROM,SAVESTATE = sys.argv[1:] + [""]*(3-len(sys.argv))
OUTPUTFILE = "output.txt"
OutputHandle = None
OutputState = False
FileLimit = 10*2**20
Format = "line"
UserVars = {}
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

    [identifier][op][expression]    create/modify a User Variable; "op" may be =, +=, -=, *=, etc
                                        if identifier is r0-r16 or sp/lr/pc, changes a register value
                                        if identifier is m(addr,size), changes a value in memory
    dv [identifier]                 delete user variable
    vars                            print all user variables
    save (identifier)               create a local save; identifier = PRIORSTATE by default
    load (identifier)               load a local save; identifier = PRIORSTATE by default
    ds [identifier]                 delete local save
    saves                           print all local save identifiers

    importrom [filepath]            import a rom into the debugger
    importstate [filepath]          import a savestate
    output [arg]                    if arg is "True", outputs to "output.txt"; if arg is "False", does not output
                                        if arg is "clear", deletes the data in "output.txt"
    format [preset]                 set the format of data sent to the output file
                                        presets: line / block / linexl / blockxl  (xl suffix for Excel formatting)
    cls                             clear the console
    help/?                          print the help text
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
    string = re.sub("[a-zA-Z]\w*", lambda x: str(reps[x.group(0)]) if x.group(0) in reps else x.group(0), string)
    reps = {"\$":"0x", "#":"", r"\bx":"0x", r"r(\d+)":r"Reg[\1]", r"m\((.*)\)":r"mem_read(\1)"}
    for k,v in reps.items(): string = re.sub(k,v,string)
    return string


def expeval(args): return eval(expstr(str(args)))


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
        outstring = f"{Addr:0>8X}: {instr:0>{2*Size}X}".ljust(20) + f"{disasm(instr,Mode,PC)[:20]}".ljust(22) + f"CPSR: [{cpsr}]"
        for i in range(16): 
            outstring += f"  R{i:0>2}: {Reg[i]:0>8x}"
    elif preset == "block":
        outstring = f"{Addr:0>8X}: {instr:0>{2*Size}X}".ljust(20) + f"{disasm(instr,Mode,PC)}"
        for i in range(16):
            if i%4 == 0: outstring += "\n"
            outstring += f"  R{i:0>2}: {Reg[i]:0>8x}"
        outstring += f"\n  CPSR: [{cpsr}]  {Reg[16]:0>8X}\n"
    elif preset == "linexl":
        outstring = f"{Addr:0>8X}:\t{instr:0>{2*Size}X}\t{disasm(instr,Mode,PC)}\tCPSR: [{cpsr}]"
        for i in range(16): 
            outstring += f"\tR{i:0>2}: {Reg[i]:0>8x}"
    elif preset == "blockxl":
        outstring = f"{Addr:0>8X}:\t{instr:0>{2*Size}X}\t{disasm(instr,Mode,PC)}\t\tCPSR: [{cpsr}]"
        for i in range(16):
            if i%4 == 0: outstring += "\n"
            outstring += f"\tR{i:0>2}: {Reg[i]:0>8x}"
        outstring += "\n"
    OutputHandle.write(outstring + "\n")


def com_n(count=1): 
    global Show,Pause,PauseCount
    Show,Pause,PauseCount = True, False, expeval(count)
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
def com_i(): showreg()
def com_dist(addr,count=1): disT(expeval(addr), expeval(count))
def com_disa(addr,count=1): disA(expeval(addr), expeval(count))
def com_m(addr,count=1,size=4): hexdump(expeval(addr),expeval(count),expeval(size))
def com_setm(addr,data,size=4): mem_write(expeval(addr), expeval(data), expeval(size))
def com_setr(regnum,value):
    regnum = re.sub(r"^r(\d+)$", r"\1", regnum)
    reps = {"sp":"13","lr":"14","pc":"15"}
    if regnum in reps: regnum = reps[regnum]
    Reg[expeval(regnum)] = expeval(value)
def com_dv(identifier): del UserVars[identifier]
def com_vars(): print(UserVars)
def com_save(identifier="PRIORSTATE"):
    LocalSaves[identifier] = [], Reg.copy()
    for i in range(8): LocalSaves[identifier][0].append(Memory[i].copy())
def com_load(identifier="PRIORSTATE"):
    for i in range(8): Memory[i] = LocalSaves[identifier][0][i].copy()
    Reg[:] = LocalSaves[identifier][1].copy()
def com_ds(identifier): del LocalSaves[identifier]
def com_saves(): print(list(LocalSaves))
def com_importrom(*args): importrom(" ".join(args).strip('"'))
def com_importstate(*args): importstate(" ".join(args).strip('"'))
def com_output(arg):
    global OutputHandle, OutputState
    arg = arg.lower()
    if arg == "true": 
        if not OutputHandle: OutputHandle = open(OUTPUTFILE,"w+")
        else: OutputHandle = open(OUTPUTFILE,"r+"); OutputHandle.seek(0,2)
        OutputState = True
    elif arg == "false": OutputHandle.close(); OutputState = False
    elif arg == "clear": open(OUTPUTFILE,"w").close(); OutputHandle.seek(0)
def com_format(arg): global Format; Format = arg
def com_cls(): os.system("cls")
def com_help(): print(helptext[1:-1])
def com_quit(): quit()
def com_e(): global lastcommand,ExecMode; lastcommand = ""; ExecMode = True

commands = {
    "n":com_n, "c":com_c, "b":com_b, "bw":com_bw, "br":com_br, "bc":com_bc, "d":com_d, "dw":com_dw, "dr":com_dr, "dc":com_dc, 
    "i":com_i, "dist":com_dist, "disa":com_disa, "m":com_m, "setm":com_setm, "setr":com_setr, "dv":com_dv, "vars":com_vars, 
    "save":com_save, "load":com_load, "ds":com_ds, "saves":com_saves, "importrom":com_importrom, "importstate":com_importstate, 
    "output":com_output, "format":com_format, "cls":com_cls, "help":com_help, "?":com_help, "quit":com_quit, "exit":com_quit, 
    "e":com_e}
assignments = {"","+","-","*","//","/","&","^","%","<<",">>","**"}


Show = True
Pause = True
PauseCount = 0
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

                # Assignment operators
                op = re.search(r"([^ a-zA-Z0-9]*)=",command)
                if op and op.group(1) in assignments:
                    identifier,expression = command.replace(" ","").split(op.group(0))
                    op = op.group(0)
                    expression = expeval(expression)
                    matchr = re.match(r"r(\d+)$",identifier)
                    matchm = re.match(r"m\(([^,]+),?(.+)?\)",identifier)
                    if matchr: exec(f"Reg[{int(matchr.group(1))}]{op}{expression}")
                    elif matchm:
                        arg0,arg1 = expeval(matchm.group(1)), expeval(matchm.group(2))
                        if arg1 == None: arg1 = 4
                        newvalue = mem_read(arg0,arg1)
                        exec(f"newvalue{op}{expression}")
                        mem_write(arg0, newvalue, arg1)
                    else: exec(f"UserVars[identifier]{op}{expression}")

                # Command execution
                else: 
                    try: com = commands[name]
                    except KeyError: 
                        try: print(expeval(command))
                        except NameError: print("Unrecognized command")
                    else: com(*args)
        except Exception:
            print(traceback.format_exc(),end="")
    else:
        if not Memory[8]: 
            print("Error: No ROM loaded")
            Pause = True
            continue

    # Find next instruction
    Mode = Reg[16]>>5 & 1
    Size = 4 - 2*Mode
    PC = Reg[15] + Size
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
        print(f"{Addr:0>8X}: {instr:0>{2*Size}X}".ljust(19), disasm(instr, Mode, PC))
        showreg()
    if OutputState:
        writefile(Format)
        if OutputHandle.tell() > FileLimit:
            order = max(0,(int.bit_length(FileLimit)-1)//10)
            message = f"Warning: output file has exceeded {FileLimit//2**(10*order)} {('','K','M','G')[order]}B"
            print(f"{'~'*len(message)}\n{message}\n{'~'*len(message)}")
            s = input("Proceed? y/n: ")
            if s.lower() in {"y","yes"}: FileLimit *= 4
            else: Pause = True
