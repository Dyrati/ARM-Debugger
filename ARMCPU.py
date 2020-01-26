import os,sys,gzip,traceback
from bisect import bisect_right


# Initialization #

ROM,SAVESTATE = sys.argv[1:] + [""]*(3-len(sys.argv))
LocalSaves = {}

def reset_memory():
    global Memory, registers, Mode

    Memory = [
        bytearray(0x4000),      #BIOS
        None,                   #Not used
        bytearray(0x40000),     #WRAM
        bytearray(0x8000),      #IRAM
        bytearray(0x400),       #I/O
        bytearray(0x400),       #PALETTE
        bytearray(0x18000),     #VRAM
        bytearray(0x400),       #OAM
        None,                   #ROM
    ]

    registers = [0]*17
    registers[0] = 0x08000000
    registers[1] = 0x000000EA
    registers[13] = 0x03007f00
    registers[15] = 0x08000004
    Mode = 0


def importrom(filepath):
    reset_memory()
    with open(filepath,"rb") as f:
        Memory[8] = bytearray(f.read())
        
def importstate(filepath):
    global Memory, registers, Mode
    locations = [(2,0x8400,0x48400),(3,0x0,0x8000),(4,0x8ea08,0x8ee08),(5,0x8000,0x8400),(6,0x48400,0x60400),(7,0x68400,0x68800)]
    with gzip.open(filepath,"rb") as f:
        save = bytearray(f.read())
    for region,start,end in locations:
        Memory[region] = save[start+0x1df:end+0x1df]
    for i in range(16):
        registers[i] = int.from_bytes(save[24+4*i:28+4*i],"little")
    registers[16] = save[91] >> 4
    Mode = save[88] >> 5 & 1
    LocalSaves["PRIORSTATE"] = Memory.copy(), registers.copy(), Mode


reset_memory()
if ROM: importrom(ROM)
if SAVESTATE: importstate(SAVESTATE)


helptext = """
    [] required args;  () optional args

    Commands                    Effect
                                (empty) repeat the previous command
    n (count)                   execute the next instruction(s), displaying the registers; count=1 by default
    c (count)                   continue execution (if count is omitted, continues forever)
    b [addr]                    set breakpoint (if addr is 'all', prints all breakpoints, watchpoints, and readpoints)
    bw [addr]                   set watchpoint
    br [addr]                   set readpoint
    d [addr]                    delete breakpoint (if addr is 'all', deletes all breakpoints, watchpoints, and readpoints)
    dw [addr]                   delete watchpoint
    dr [addr]                   delete readpoint
    i                           print the registers
    m [addr] (count) (size)     display the memory at addr (count=1, size=4 by default)
    h/help/?                    print the help text
    importrom [filepath]        import a rom into the debugger
    importstate [filepath]      import a savestate; PRIORSTATE becomes a copy of this state
    save (identifier)           save the current state locally, with the name *identifier*;
                                  if identifier is omitted, saves to PRIORSTATE
    load (identifier)           load a local state; if identifier is omitted, loads PRIORSTATE
    localsaves                  print all local save identifiers
    cls                         clear the console
    quit/exit                   exit the program
    e                           switch to Execution Mode
                                  In this mode, you may type in valid code which will be executed.
                                  Enter nothing to return to Normal Mode.
"""


def undef(*args): pass


def mem_read(addr,size):
    region = Memory[addr >> 24 & 0xF]
    reladdr = addr % len(region)
    value = int.from_bytes(region[reladdr:reladdr+size],"little")
    if addr in ReadPoints:
        global BreakState
        BreakState = f"ReadPoint: {addr:0>{2*size}X} (={value:0>{2*size}X})"
    return value


def mem_readsigned(addr,size):
    region = Memory[addr >> 24 & 0xF]
    reladdr = addr % len(region)
    value = int.from_bytes(region[reladdr:reladdr+size],"little")
    msb = 2**(8*size-1)
    value = ((value^msb) - msb) & 0xFFFFFFFF
    if addr in ReadPoints:
        global BreakState
        BreakState = f"ReadPoint: {addr:0>{2*size}X} (={value:0>{2*size}X})"
    return value


def mem_write(addr,data,size):
    region = Memory[addr >> 24 & 0xF]
    reladdr = addr % len(region)
    value = int.to_bytes(data % 2**(8*size),size,"little")
    if addr in WatchPoints:
        global BreakState
        newvalue = int.from_bytes(value,"little")
        BreakState = f"WatchPoint: {addr:0>8X} ({mem_read(addr,size):0>{2*size}X} -> {newvalue:0>{2*size}X})"
    region[reladdr:reladdr+size] = value


def mem_copy(src,des,size):
    region1 = Memory[src >> 24 & 0xF]
    region2 = Memory[des >> 24 & 0xF]
    src %= len(region1)
    des %= len(region2)
    copydata = region1[src:src + size]
    if src + size > len(region1): 
        copydata += region1[:(src + size) % len(region1)]
    if des + size > len(region2):
        distance = len(region2) - des
        region2[des:] = copydata[:distance]
        region2[:size-distance] = copydata[distance:size-distance]
    else:
        region2[des:des+size] = copydata


def DMA():
    src = mem_read(0x040000D4,4)
    des = mem_read(0x040000D8,4)
    count = mem_read(0x040000DC,2)
    control = mem_read(0x040000DE,2)
    mem_copy(src, des, count*(2 + 2*(control >> 10 & 1)))
    mem_write(0x040000DE, control & 0x7FFF, 2)


def compare(r,Op1,Op2,S=1):
    result = (Op1 & 0xFFFFFFFF) + (Op2 & 0xFFFFFFFF)
    sign1 = Op1 >> 30
    sign2 = Op2 >> 30
    N = 8 if result & 2**31 else 0
    Z = 4 if not result & 0xFFFFFFFF else 0
    C = 2 if result & 2**32 else 0
    V = 1 if sign1 == sign2 != N else 0
    if S: r[16] = N|Z|C|V
    return result & 0xFFFFFFFF


def cmphalf(r,result,S=1):
    result &= 0xFFFFFFFF
    N = 8 if result & 2**31 else 0
    Z = 4 if not result else 0
    if S: r[16] = N|Z | r[16] & 3
    return result


def barrelshift(r,value,Shift,Typ,S=0):
    value &= 0xFFFFFFFF
    if Typ == 3: Shift &= 31
    else: Shift = min(32,Shift)
    affectedflags = 0xE
    if Shift: 
        C = 2*min(1, value & 1 << Shift-1)
        if Typ == 0: value <<= Shift; C = value >> 32 & 1
        elif Typ == 1: value >>= Shift
        elif Typ == 2: value = (value ^ 2**31) - 2**31 >> Shift
        elif Typ == 3: value = ((value & 2**Shift-1) << 32 | value) >> Shift
    else:
        C = 2*(value>>31)
        if Typ == 0: affectedflags = 0xC; C = 0
        elif Typ == 1: value = 0
        elif Typ == 2: value = -(value>>31)
        elif Typ == 3: value = ((r[16] & 2) << 31 | value) >> 1
    value &= 0xFFFFFFFF
    N = 8 if value & 2**31 else 0
    Z = 4 if not value else 0
    if S: r[16] = r[16] & ~affectedflags | N|Z|C
    return value


conditions = (
    lambda cpsr: cpsr & 4 == 4,             # EQ: Z=1
    lambda cpsr: cpsr & 4 == 0,             # NE: Z=0
    lambda cpsr: cpsr & 2 == 2,             # CS/HS: C=1
    lambda cpsr: cpsr & 2 == 0,             # CC/LO: C=0
    lambda cpsr: cpsr & 8 == 8,             # MI: N=1
    lambda cpsr: cpsr & 8 == 0,             # PL: N=0
    lambda cpsr: cpsr & 1 == 1,             # VS: V=1
    lambda cpsr: cpsr & 1 == 0,             # VC: V=0
    lambda cpsr: cpsr & 6 == 2,             # HI: C=1 and Z=0
    lambda cpsr: cpsr & 6 != 2,             # LS: C=0 or Z=1
    lambda cpsr: cpsr & 9 in {0,9},         # GE: N=V
    lambda cpsr: cpsr & 9 not in {0,9},     # LT: N!=V
    lambda cpsr: cpsr & 13 in {0,9},        # GT: Z=0 and N=V
    lambda cpsr: cpsr & 13 in {5,12},       # LE: Z=1 and N!=V
    lambda cpsr: True,                      # AL: Always true
    lambda cpsr: False,                     # NV: Never true
)


#####################
## THUMB FUNCTIONS ##
#####################


def shifted(r,instr):
    Op,Offset,Rs,Rd = instr>>11 & 3, instr>>6 & 31, instr>>3 & 7, instr & 7
    r[Rd] = barrelshift(r,r[Rs],Offset,Op,1)


def addsub(r,instr):
    I,Op,Rn,Rs,Rd = instr>>10 & 1, instr>>9 & 1, instr>>6 & 7, instr>>3 & 7, instr & 7
    Rs = r[Rs]
    if not I: Rn = r[Rn]
    if not Op: r[Rd] = compare(r,Rs,Rn)
    else: r[Rd] = compare(r,Rs,-Rn)
    

def immediate(r,instr):
    Op,Rd,Offset = instr>>11 & 3, instr>>8 & 7, instr & 0xFF
    Op1 = r[Rd]
    if Op == 0: r[Rd] = cmphalf(r,Offset)
    elif Op == 1: compare(r, r[Rd], -Offset)
    elif Op == 2: r[Rd] = compare(r, r[Rd], Offset)
    elif Op == 3: r[Rd] = compare(r, r[Rd],-Offset)


alu_ops = (
    lambda r,Rd,Rs: cmphalf(r, Rd & Rs),                        # AND
    lambda r,Rd,Rs: cmphalf(r, Rd ^ Rs),                        # XOR
    lambda r,Rd,Rs: barrelshift(r,Rd,Rs & 0x1F,0,1),            # LSL
    lambda r,Rd,Rs: barrelshift(r,Rd,Rs & 0x1F,1,1),            # LSR
    lambda r,Rd,Rs: barrelshift(r,Rd,Rs & 0x1F,2,1),            # ASR
    lambda r,Rd,Rs: compare(r, Rd, Rs + (r[16]>>1 & 1)),        # ADC
    lambda r,Rd,Rs: compare(r, Rd,-Rs + (r[16]>>1 & 1) - 1),    # SBC
    lambda r,Rd,Rs: barrelshift(r,Rd,Rs & 0x1F,3,1),            # ROR
    lambda r,Rd,Rs: cmphalf(r,Rd & Rs),                         # TST
    lambda r,Rd,Rs: compare(r, 0,-Rs),                          # NEG
    lambda r,Rd,Rs: compare(r, Rd,-Rs),                         # CMP
    lambda r,Rd,Rs: compare(r, Rd, Rs),                         # CMN
    lambda r,Rd,Rs: cmphalf(r, Rd | Rs),                        # ORR
    lambda r,Rd,Rs: cmphalf(r, Rd * Rs),                        # MUL
    lambda r,Rd,Rs: cmphalf(r, Rd & ~Rs),                       # BIC
    lambda r,Rd,Rs: cmphalf(r, ~Rs),                            # MVN
)

def AluOp(r,instr):
    Op,Rs,Rd = instr>>6 & 15, instr>>3 & 7, instr & 7
    result = alu_ops[Op](r,r[Rd],r[Rs])
    if Op not in {8,10,11}: r[Rd] = result


def HiRegBx(r,instr):
    Op,Hd,Hs,Rs,Rd = instr>>8 & 3, instr>>7 & 1, instr>>6 & 1, instr>>3 & 7, instr & 7
    Rd += 8*Hd
    Rs += 8*Hs
    if Op == 0: r[Rd] += r[Rs]
    elif Op == 1: compare(r, r[Rd],-r[Rs])
    elif Op == 2: r[Rd] = r[Rs]
    elif Op == 3:
        global Mode
        Mode = r[Rs] & 1
        if Hd: r[14] = r[15] + 1
        r[15] = r[Rs] + 4-3*Mode


def ldr_pc(r,instr):
    Rd,Word = instr>>8 & 7, instr & 0xFF
    r[Rd] = mem_read(r[15] + Word*4 - (r[15] & 2), 4)


def ldrstr(r,instr):
    Op,S,Ro,Rb,Rd = instr>>10 & 3, instr>>9 & 1, instr>>6 & 7, instr>>3 & 7, instr & 7
    addr = r[Rb] + r[Ro]
    if not S:
        if Op == 0: mem_write(addr, r[Rd], 4)
        elif Op == 1: mem_write(addr, r[Rd], 1)
        elif Op == 2: r[Rd] = mem_read(addr, 4)
        elif Op == 3: r[Rd] = mem_read(addr, 1)
    else:
        if Op == 0: mem_write(addr, r[Rd], 2)
        elif Op == 1: r[Rd] = mem_readsigned(addr, 1)
        elif Op == 2: r[Rd] = mem_read(addr, 2)
        elif Op == 3: r[Rd] = mem_readsigned(addr, 2)


def ldrstr_imm(r,instr):
    Op,L,Offset,Rb,Rd = instr>>12 & 3, instr>>11 & 1, instr>>6 & 31, instr>>3 & 7, instr & 7
    size = Op^2 if Op != 2 else 4  # (3,2,0) -> (1,4,2)
    addr = r[Rb] + Offset*size
    if not L: mem_write(addr, r[Rd], size)
    else: r[Rd] = mem_read(addr, size)


def ldrstr_sp(r,instr):
    Op,Rd,Word = instr>>11 & 1, instr>>8 & 7, instr & 0xFF
    if not Op: mem_write(r[13] + Word*4, r[Rd], 4)
    else: r[Rd] = mem_read(r[13] + Word*4, 4)


def get_reladdr(r,instr):
    Op,Rd,Word = instr>>11 & 1, instr>>8 & 7, instr & 0xFF
    if not Op: r[Rd] = r[15] - (r[15] & 2) + Word*4
    else: r[Rd] = r[13] + Word*4


def add_sp(r,instr):
    S,Word = instr>>7 & 1, instr & 0x7F
    if not S: r[13] += Word*4
    else: r[13] -= Word*4


def pushpop(r,instr):
    Op,Rlist = instr>>11 & 1, instr & 0x1FF
    Rlist = [i for i in range(9) if Rlist & 2**i]
    if Rlist[-1] == 8: Rlist[-1] = 14 + Op
    if not Op:
        for i in reversed(Rlist):
            r[13] -= 4
            mem_write(r[13], r[i], 4)
    else:
        for i in Rlist:
            r[i] = mem_read(r[13], 4)
            r[13] += 4
        if r[15] & 1: r[15] += 1


def stmldm(r,instr):
    Op,Rb,Rlist = instr>>11 & 1, instr>>8 & 7, instr & 0xFF
    addr = r[Rb]
    for i in range(8):
        if Rlist & 2**i:
            if not Op: mem_write(addr, r[i], 4)
            else: r[i] = mem_read(addr, 4)
            addr += 4
    r[Rb] = addr


def b_if(r,instr):
    Cond,Offset = instr>>8 & 15, instr & 0xFF
    if conditions[Cond](r[16]): r[15] += ((Offset^0x80) - 0x80)*2 + 2


def branch(r,instr):
    r[15] += ((instr & 0x7FF ^ 0x400) - 0x400)*2 + 2


def bl(r,instr):
    if instr == 0xF800:
        link = r[15] - 1
        r[15] = r[14] + 2
        r[14] = link
    else:
        r[14] = r[15] + 1
        r[15] += (((instr & 0x7FF ^ 0x400) << 11 | (instr >> 16) & 0x7FF) - 0x200000)*2 + 2


ThumbBounds = (
    0x1800,0x2000,0x4000,0x4400,0x4800,0x5000,0x6000,0x8000,0x9000,0xA000,
    0xB000,0xB400,0xBE00,0xC000,0xD000,0xDE00,0xDF00,0xE000,0xE800,0xF000,
)

ThumbFuncs = (
    shifted, addsub, immediate, AluOp, HiRegBx, ldr_pc, ldrstr, ldrstr_imm, ldrstr_imm, ldrstr_sp,
    get_reladdr, add_sp, pushpop, undef, stmldm, b_if, undef, undef, branch, undef, bl
)



###################
## ARM FUNCTIONS ##
###################


dataprocess_list = (
    lambda r,Rn,Op2,S: cmphalf(r, Rn & Op2, S),                        # AND
    lambda r,Rn,Op2,S: cmphalf(r, Rn ^ Op2, S),                        # EOR
    lambda r,Rn,Op2,S: compare(r, Rn, -Op2, S),                        # SUB
    lambda r,Rn,Op2,S: compare(r, Op2, -Rn, S),                        # RSB
    lambda r,Rn,Op2,S: compare(r, Rn, Op2, S),                         # ADD
    lambda r,Rn,Op2,S: compare(r, Rn, Op2 + (r[16]>>1 & 1), S),        # ADC
    lambda r,Rn,Op2,S: compare(r, Rn,-Op2 + (r[16]>>1 & 1) - 1, S),    # SBC
    lambda r,Rn,Op2,S: compare(r, Op2,-Rn + (r[16]>>1 & 1) - 1, S),    # RSC
    lambda r,Rn,Op2,S: cmphalf(r, Rn & Op2, S),                        # TST
    lambda r,Rn,Op2,S: cmphalf(r, Rn ^ Op2, S),                        # TEQ
    lambda r,Rn,Op2,S: compare(r, Rn, -Op2, S),                        # CMP
    lambda r,Rn,Op2,S: compare(r, Rn, Op2, S),                         # CMN
    lambda r,Rn,Op2,S: cmphalf(r, Rn | Op2, S),                        # ORR
    lambda r,Rn,Op2,S: cmphalf(r, Op2, S),                             # MOV
    lambda r,Rn,Op2,S: cmphalf(r, Rn & ~Op2, S),                       # BIC
    lambda r,Rn,Op2,S: cmphalf(r,~Op2, S),                             # MVN
)


def dataprocess(r,instr):
    i = instr
    Imm, OpCode, S, Rn, Rd, Shift, Typ, Imm2, Rm = (
        i>>25 & 1, i>>21 & 15, i>>20 & 1, i>>16 & 15, i>>12 & 15, i>>7 & 31, i>>5 & 3, i>>4 & 1, i & 15)
    if Imm:
        Op2 = i & 0xFF
        Shift = (i >> 8 & 15)*2
        Op2 = ((Op2 & 2**Shift-1) << 32 | Op2) >> Shift
    else:
        Op2 = r[Rm]
        if Imm2: Shift = r[Shift>>1 & 15]
        Op2 = barrelshift(r,Op2,Shift,Typ,S)
    result = dataprocess_list[OpCode](r,r[Rn],Op2,S)
    if not(8 <= OpCode <= 11): 
        r[Rd] = result


def arm_bx(r,instr):
    global Mode
    L, Rn = instr >> 5 & 1, instr & 15
    if L: r[14] = r[15] - 4
    Mode = r[Rn] & 1
    r[15] = r[Rn] + 4-3*Mode


def arm_branch(r,instr):
    L, Offset = instr >> 24 & 1, instr & 0xFFFFFF
    if L: r[14] = r[15] - 4
    r[15] += 4 + Offset*4


def clz(r,instr):
    Rd,Rm = instr >> 12 & 15, instr & 15    
    r[Rd] = 32 - int.bit_length(r[Rm])


def multiply(r,instr):
    i = instr
    OpCode, S, Rd, Rn, Rs, y, x, Rm = (i>>21 & 15, i>>20 & 1, i>>16 & 15, i>>12 & 15, i>>8 & 15, i>>6 & 1, i>>5 & 1, i & 15)
    Rm, Rs = r[Rm], r[Rs]
    if OpCode & 8:  #half registers
        OpCode &= 3
        S = 0
        Rs = (Rs >> 16*y & 0xFFFF ^ 2**15) - 2**15
        if OpCode & 1: Rm = (Rm ^ 2**31) - 2**31
        else: Rm = (Rm >> 16*x & 0xFFFF ^ 2**15) - 2**15
        if OpCode == 0: r[Rd] = (Rm*Rs + r[Rn]) % 2**32
        elif OpCode == 1: r[Rd] = ((Rm*Rs >> 16) + r[Rn]*y) % 2**32
        elif OpCode == 2:
            result = (r[Rd] << 32 | r[Rn]) + Rm*Rs
            r[Rd] = result >> 32 & 0xFFFFFFFF
            r[Rn] = result & 0xFFFFFFFF
        elif OpCode == 3:
            r[Rd] = Rm*Rs
    else:
        if OpCode & 2:  #signed
            Rm = (Rm ^ 2**31) - 2**31
            Rs = (Rs ^ 2**31) - 2**31
        result = Rm*Rs + r[Rn]*(OpCode & 1)
        if OpCode & 4: 
            r[Rd] = result >> 32 & 0xFFFFFFFF
            r[Rn] = result & 0xFFFFFFFF
        else: 
            r[Rd] = result & 0xFFFFFFFF
        if S:
            N,Z = 0,0
            if result & 2**63: N = 8
            if not result: Z = 4
            r[16] = N|Z|(r[16] & 3)


def datatransfer(r,instr):
    Flags, Rn, Rd, Offset = (instr>>20 & 0x7F, instr>>16 & 15, instr>>12 & 15, instr & 0xFFF)
    #Flags: Single/Double, Immediate offset, Pre/Post index, Up/Down, Byte/Int, Writeback, Load/Store
    D,I,P,U,B,W,L = (1 if Flags & 2**(6-i) else 0 for i in range(7))
    Shift, Typ, Rm = Offset>>7 & 31, Offset>>5 & 3, Offset & 15
    U = (-1,1)[U]
    addr = r[Rn]
    if D:
        if I: Offset = barrelshift(r,r[Rm],Shift,Typ)
        if P: addr += Offset*U
        if not P or W: r[Rn] += Offset*U
        if L: r[Rd] = mem_read(addr, 4 - 3*B)
        else: mem_write(addr, r[Rd], 4 - 3*B)
    else:
        Rm = Offset & 15
        # B is Immediate offset flag when D is set
        if B: Offset = (Offset >> 8 & 15) << 4 | Offset & 15
        else: Offset = r[Rm]
        if P: addr += Offset*U
        if not P or W: r[Rn] += Offset*U
        if Typ == 0:
            temp = r[Rm]  # in case Rm == Rd
            r[Rd] = mem_read(r[Rn],2-B)
            mem_write(r[Rn],temp,2-B)
        elif L:
            if Typ == 1: r[Rd] = mem_read(addr,2)
            elif Typ == 2: r[Rd] = mem_readsigned(addr,1)
            elif Typ == 3: r[Rd] = mem_readsigned(addr,2)
        else:
            if Typ == 1: mem_write(addr,r[Rd],2)
            elif Typ == 2: r[Rd],r[Rd+1] = mem_read(addr,4), mem_read(addr + 4,4)
            elif Typ == 3: mem_write(addr,r[Rd],4); mem_write(addr + 4,r[Rd+1],4)


def blocktransfer(r,instr):
    Flags,Rn,Rlist = instr>>20 & 31, instr>>16 & 15, instr & 0xFFFF
    #Flags: Pre/Post, Up/Down, Load PSR, Writeback, Load/Store
    P,U,S,W,L = (1 if Flags & 2**(4-i) else 0 for i in range(5))
    direction = (-1,1)[U]
    addr = r[Rn]
    if P: addr += 4*direction
    index = (15,0)[U]
    for i in range(16):
        if Rlist & 1<<index:
            if L: r[index] = mem_read(addr,4)
            else: mem_write(addr,r[index],4)
            addr += 4*direction
        index += direction
    if P: addr -= 4*direction
    if W: r[Rn] = addr


arm_tree = {
    0:(27,36), 1:(26,31), 2:(25,28), 3:(4,9), 4:([25<<20,16<<20],6), 5:dataprocess, 6:(7,8), 7:undef, 
    8:multiply, 9:(7,19), 10:([25<<20,16<<20],12), 11:dataprocess, 12:(6,16), 13:(22,15), 14:arm_bx, 15:clz, 
    16:(5,18), 17:undef, 18:undef, 19:([3<<5,0],23), 20:(22,22), 21:datatransfer, 22:datatransfer, 23:(24,27), 
    24:(23,26), 25:multiply, 26:multiply, 27:datatransfer, 28:([25<<20,16<<20],30), 29:dataprocess, 30:undef, 31:(25,33), 
    32:datatransfer, 33:(4,35), 34:datatransfer, 35:undef, 36:(26,40), 37:(25,39), 38:blocktransfer, 39:arm_branch,
    40:(25,44), 41:([15<<21,2<<21],43), 42:undef, 43:undef, 44:(24,48), 45:(4,47), 46:undef, 47:undef,
    48:undef
}


def navigateTree(instr,tree):
    treepos = 0
    while True:
        try: 
            condition = tree[treepos][0]
            if type(condition) == int:
                if instr>>condition & 1: treepos = tree[treepos][1]
                else: treepos += 1
            else:
                bitmask,value = condition
                if instr & bitmask == value: treepos = tree[treepos][1]
                else: treepos += 1
        except TypeError:
            return tree[treepos]


def execute(r,instr,Mode):
    # ARM
    if Mode == 0:
        r[15] += 4
        Cond = instr >> 28
        if conditions[Cond](r[16]):
            arm_function = navigateTree(instr,arm_tree)
            arm_function(r,instr)
    # THUMB
    elif Mode == 1:
        r[15] += 2
        ID = bisect_right(ThumbBounds,instr)
        ThumbFuncs[ID](r,instr)


# For Debugging #

def hexdump(addr,count=1,size=4):
    s = ""
    for i in range(count):
        if not i*size & 15:
            s += f"\n{addr:0>8X}:  "
        s += f"{mem_read(addr,size):0>{2*size}X} "
        addr += size
    print(s[1:])


def showreg():
    s = ""
    for i in range(16):
        s += f"R{i:0>2}: {registers[i]:0>8X} "
        if i & 3 == 3: s += "\n"
    cpsr = ["N","Z","C","V"]
    cpsr = [cpsr[i] if registers[16] & 2**(3-i) else "-" for i in range(4)]
    print(s + f"CPSR: [{''.join(cpsr)}]")
    

Show = True
Pause = True
PauseCount = 0
BreakPoints = set()
WatchPoints = set()
ReadPoints = set()
BreakState = ""
lastcommand = [""]
ExecMode = False

while True:

    # Interface
    while Pause:
        try:
            if ExecMode:
                command = input(">> ")
                if command == "": ExecMode = False
                else: exec(command)
            else:
                command = input("> ").strip().split(" ")
                if command[0] == "": command = lastcommand
                lastcommand = command.copy()
                name,args = command[0].lower(),command[1:]
                if name == "n": 
                    Show,Pause = True,False
                    try: PauseCount = int(args[0])
                    except IndexError: PauseCount = 1
                elif name == "c": 
                    Show,Pause = False,False
                    try: PauseCount = int(args[0])
                    except IndexError: PauseCount = 0
                elif name == "b":
                    if args[0] == "all":
                        print("BreakPoints:",[f"{i:0>8X}" for i in sorted(BreakPoints)])
                        print("WatchPoints:",[f"{i:0>8X}" for i in sorted(WatchPoints)])
                        print("ReadPoints: ",[f"{i:0>8X}" for i in sorted(ReadPoints)])
                    else: BreakPoints.add(int(args[0],16))
                elif name == "bw": WatchPoints.add(int(args[0],16))
                elif name == "br": ReadPoints.add(int(args[0],16))
                elif name == "d":
                    if args[0] == "all": BreakPoints,WatchPoints,ReadPoints = set(),set(),set()
                    else: BreakPoints.remove(int(args[0],16))
                elif name == "dw": WatchPoints.remove(int(args[0],16))
                elif name == "dr": ReadPoints.remove(int(args[0],16))
                elif name == "i": showreg()
                elif name == "m": hexdump(int(args[0],16),*(int(i) for i in args[1:]))
                elif name in {"h","help","?"}: print(helptext)
                elif name == "e": lastcommand = [""]; ExecMode = True
                elif name == "importrom": importrom(" ".join(command[1:]).strip('"'))
                elif name == "importstate": importstate(" ".join(command[1:]).strip('"'))
                elif name == "save": 
                    try: identifier = args[0]
                    except IndexError: identifier = "PRIORSTATE"
                    LocalSaves[identifier] = Memory.copy(), registers.copy(), Mode
                elif name == "load": 
                    try: identifier = args[0]
                    except IndexError: identifier = "PRIORSTATE"
                    Memory,registers,Mode = LocalSaves[identifier]
                    Memory,registers = Memory.copy(), registers.copy()
                elif name == "localsaves": print(list(LocalSaves))
                elif name == "cls": os.system("cls")
                elif name in {"quit","exit"}: quit()
                else: print("Unrecognized command")
        except Exception:
            print(traceback.format_exc(),end="")
    else:
        if Memory[8] == None: 
            print("Error: No ROM loaded")
            Pause = True
            continue

    # Find next instruction
    size = 4 - 2*Mode
    addr = registers[15]-size
    addr -= addr & size-1
    if addr in BreakPoints: BreakState = f"BreakPoint: {addr:0>8X}"
    instr = mem_read(addr,size)
    if Mode and 0xF000 <= instr < 0xF800:
        instr = mem_read(addr,4); size = 4

    # Execute
    execute(registers,instr,Mode)
    if mem_read(0x040000DF,1) & 2**7: DMA()

    # Handlers
    if PauseCount: PauseCount -= 1; Pause = not PauseCount
    if BreakState:
        Show,Pause = True,True
        print("Hit " + BreakState)
        BreakState = ""
    if Show:
        print(f"{addr:0>8X}: {instr:0>{2*size}X}")
        showreg()
