from os import system
from bisect import bisect_right
import sys
import gzip


def undef(*args): pass

def mem_read(addr,size):
    region = Memory[addr >> 24 & 0xF]
    addr %= len(region)
    return int.from_bytes(region[addr:addr+size],"little")

def mem_readsigned(addr,size):
    region = Memory[addr >> 24 & 0xF]
    addr %= len(region)
    value = int.from_bytes(region[addr:addr+size],"little")
    msb = 2**(8*size-1)
    return ((value^msb) - msb) & 0xFFFFFFFF

def mem_write(addr,data,size):
    region = Memory[addr >> 24 & 0xF]
    addr %= len(region)
    region[addr:addr+size] = int.to_bytes(data % 2**(8*size),size,"little")

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


def barrelshift(r,value,Shift,Typ,S=0):
    value &= 0xFFFFFFFF
    if Typ == 3: Shift &= 31
    else: Shift = min(32,Shift)
    if Shift: 
        C = 2*min(1, value & 1 << Shift-1)
        if Typ == 0: value <<= Shift; C = value >> 32 & 1
        elif Typ == 1: value >>= Shift
        elif Typ == 2: value = (value ^ 2**31) - 2**31 >> Shift
        elif Typ == 3: value = ((value & 2**Shift-1) << 32 | value) >> Shift
    else:
        C = 2*(value>>31)
        if Typ == 0: S=0
        elif Typ == 1: value = 0
        elif Typ == 2: value = -(value>>31)
        elif Typ == 3: value = ((r[16] & 2) << 31 | value) >> 1
    if S: r[16] = r[16] & 13 | C
    return value & 0xFFFFFFFF


def calculateflags(result):
    # result must have infinite precision for C and V flags
    N,Z,C,V = 0,0,0,0
    if result & 2**31: N = 8
    if not result & 0xFFFFFFFF: Z = 4
    if result & 2**32: C = 2
    if (result<0) ^ (N>0): V = 1
    return N|Z|C|V


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
    if not Op: result = Rs + Rn
    else: result = (Rs^2**31) - (Rn^2**31) ^ 2**32
    r[Rd] = result & 0xFFFFFFFF
    r[16] = calculateflags(result)
    
def immediate(r,instr):
    Op,Rd,Offset = instr>>11 & 3, instr>>8 & 7, instr & 0xFF
    Op1 = (r[Rd]^2**31) - 2**31
    if Op == 0: result = Offset
    elif Op == 1: result = Op1 - Offset ^ 2**32
    elif Op == 2: result = Op1 + Offset
    elif Op == 3: result = Op1 - Offset ^ 2**32
    if Op != 1: r[Rd] = result & 0xFFFFFFFF
    r[16] = calculateflags(result)

alu_ops = (
    lambda r,Rd,Rs: (Rd & Rs, 0xC),                         # AND
    lambda r,Rd,Rs: (Rd ^ Rs, 0xC),                         # XOR
    lambda r,Rd,Rs: (barrelshift(r,Rd,Rs & 0x1F,0,1), 0),   # LSL
    lambda r,Rd,Rs: (barrelshift(r,Rd,Rs & 0x1F,1,1), 0),   # LSR
    lambda r,Rd,Rs: (barrelshift(r,Rd,Rs & 0x1F,2,1), 0),   # ASR
    lambda r,Rd,Rs: (Rd + Rs + (r[16]>>1 & 1), 0xF),        # ADC
    lambda r,Rd,Rs: (Rd - Rs + (r[16]>>1 & 1) - 1, 0xF),    # SBC
    lambda r,Rd,Rs: (barrelshift(r,Rd,Rs & 0x1F,3,1), 0),   # ROR
    lambda r,Rd,Rs: (Rd & Rs, 0xC),                         # TST
    lambda r,Rd,Rs: (-Rs, 0xF),                             # NEG
    lambda r,Rd,Rs: (Rd - Rs, 0xF),                         # CMP
    lambda r,Rd,Rs: (Rd + Rs, 0xF),                         # CMN
    lambda r,Rd,Rs: (Rd | Rs, 0xC),                         # ORR
    lambda r,Rd,Rs: (Rd * Rs, 0xC),                         # MUL
    lambda r,Rd,Rs: (Rd & ~Rs, 0xC),                        # BIC
    lambda r,Rd,Rs: (~Rs, 0xC),                             # MVN
)

def AluOp(r,instr):
    Op,Rs,Rd = instr>>6 & 15, instr>>3 & 7, instr & 7
    Op1 = (r[Rd]^2**31) - 2**31
    Op2 = (r[Rs]^2**31) - 2**31
    result,flags = alu_ops[Op](r,Op1,Op2)
    if Op not in {8,10,11}: r[Rd] = result & 0xFFFFFFFF
    r[16] = r[16] & ~flags | calculateflags(result) & flags


def HiRegBx(r,instr):
    Op,Hd,Hs,Rs,Rd = instr>>8 & 3, instr>>7 & 1, instr>>6 & 1, instr>>3 & 7, instr & 7
    Rd += 8*Hd
    Rs += 8*Hs
    if Op == 0: r[Rd] += r[Rs]
    elif Op == 1: r[16] = calculateflags((r[Rd]^2**31) - (r[Rs]^2**31) ^ 2**32)
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
    lambda r,Rn,Op2: (Rn & Op2, 0xC),                                   # AND
    lambda r,Rn,Op2: (Rn ^ Op2, 0xC),                                   # EOR
    lambda r,Rn,Op2: ((Rn - Op2) ^ 2**32, 0xF),                         # SUB
    lambda r,Rn,Op2: ((Op2 - Rn) ^ 2**32, 0xF),                         # RSB
    lambda r,Rn,Op2: (Rn + Op2, 0xF),                                   # ADD
    lambda r,Rn,Op2: (Rn + Op2 + (r[16]>>1 & 1), 0xF),                  # ADC
    lambda r,Rn,Op2: ((Rn - Op2 + (r[16]>>1 & 1) - 1) ^ 2**32, 0xF),    # SBC
    lambda r,Rn,Op2: ((Op2 - Rn + (r[16]>>1 & 1) - 1) ^ 2**32, 0xF),    # RSC
    lambda r,Rn,Op2: (Rn & Op2, 0xC),                                   # TST
    lambda r,Rn,Op2: (Rn ^ Op2, 0xC),                                   # TEQ
    lambda r,Rn,Op2: ((Rn - Op2) ^ 2**32, 0xF),                         # CMP
    lambda r,Rn,Op2: (Rn + Op2, 0xF),                                   # CMN
    lambda r,Rn,Op2: (Rn | Op2, 0xC),                                   # ORR
    lambda r,Rn,Op2: (Op2, 0xC),                                        # MOV
    lambda r,Rn,Op2: (Rn & ~Op2, 0xC),                                  # BIC
    lambda r,Rn,Op2: (~Op2, 0xC),                                       # MVN
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
        Op2 = (Op2 ^ 2**31) - 2**31
    Rn = (r[Rn] ^ 2**31) - 2**31
    result,flags = dataprocess_list[OpCode](r,Rn,Op2)
    if not(8 <= OpCode <= 11): 
        r[Rd] = result & 0xFFFFFFFF
    if S:
        r[16] = r[16] & ~flags | calculateflags(result) & flags


def arm_bx(r,instr):
    global Mode
    L, Rn = instr >> 5 & 1, instr & 15
    if L: r[14] = r[15] + 4
    Mode = r[Rn] & 1
    r[15] = r[Rn] + 4-3*Mode


def arm_branch(r,instr):
    L, Offset = instr >> 24 & 1, instr & 0xFFFFFF
    if L: r[14] = r[15] + 4
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
    index = -U % 16
    for i in range(16):
        if Rlist & 1<<i:
            if L: r[index] = mem_read(addr,4)
            else: mem_write(addr,r[index],4)
            addr += 4*direction
        index += direction
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

def mem(addr,count=1,size=4):
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



# Initialization #

def reset_memory():
    global Memory, registers
    Memory = [
        bytearray(0x4000),      #BIOS
        bytearray(0),           #Not used
        bytearray(0x40000),     #WRAM
        bytearray(0x8000),      #IRAM
        bytearray(0x400),       #I/O
        bytearray(0x400),       #PALETTE
        bytearray(0x18000),     #VRAM
        bytearray(0x400),       #OAM
        bytearray(0)            #ROM
    ]

    registers = [0]*17
    registers[0] = 0x08000000
    registers[1] = 0x000000EA
    registers[13] = 0x03007f00
    registers[15] = 0x08000004


def loadrom(filepath):
    reset_memory()
    with open(filepath,"rb") as f:
        Memory[8] = bytearray(f.read())
        
def loadstate(filepath):
    locations = [(2,0x8400,0x48400),(3,0x0,0x8000),(4,0x8ea08,0x8ee08),(5,0x8000,0x8400),(6,0x48400,0x60400),(7,0x68400,0x68800)]
    with gzip.open(filepath,"rb") as f:
        save = bytearray(f.read())
        for region,start,end in locations:
            Memory[region] = save[start+0x1df:end+0x1df]
        for i in range(16):
            registers[i] = int.from_bytes(save[24+4*i:28+4*i],"little")
        registers[16] = save[91] >> 4
        global Mode
        Mode = save[88] >> 5 & 1       

reset_memory()
try: loadrom(sys.argv[1])
except IndexError: pass
try: loadstate(sys.argv[2])
except IndexError: pass

Mode = 0
Show = True
Pause = True
Breakpoints = set()
lastcommand = [""]
ExecMode = False
helptext = """
    Commands                    Effect
                                (nothing) repeat the previous command
    n                           execute the next instruction
    c                           continue execution (if no breakpoints are set, continues infinitely)
    b [addr]                    set breakpoint (if addr is 'all', prints all breakpoints)
    d [addr]                    delete breakpoint (if addr is 'all', deletes all breakpoints)
    i                           print the registers
    m [addr] (count) (size)     display the memory at addr (count and size are optional)
    h/help/?                    print the help text
    loadrom [filepath]          load a rom into the debugger
    loadstate [filepath]        load a savestate
    cls                         clear the console
    quit                        exit the program
    e                           switch to Execution Mode
    
    In Execution Mode, you may type in valid code which will be executed.
    Enter nothing to return to Normal Mode.
"""


while True:

    while Pause:
        if ExecMode:
            command = input(">> ")
            if command == "": ExecMode = False
            else: 
                try: exec(command)
                except Exception as err: print(err.__class__.__name__ + ":",err)
        else:
            command = input("> ").strip().split(" ")
            if command[0] == "": command = lastcommand
            lastcommand = command.copy()
            if command[0] == "n": Show = True; break
            elif command[0] == "c": Pause = False; Show = False
            elif command[0] == "b":
                if command[1] == "all":
                    for i in sorted(Breakpoints): print(hex(i)[2:].zfill(8))
                else: Breakpoints.add(int(command[1],16))
            elif command[0] == "d":
                if command[1] == "all": Breakpoints = set()
                else: del Breakpoints[int(command[1],16)]
            elif command[0] == "i": showreg()
            elif command[0] == "m": mem(int(command[1],16),*(int(i) for i in command[2:]))
            elif command[0] in {"h","help","?"}: print(helptext)
            elif command[0] == "cls": system("cls")
            elif command[0] == "e": lastcommand = [""]; ExecMode = True
            elif command[0] == "loadrom": loadrom(" ".join(command[1:]).strip('"'))
            elif command[0] == "loadstate": loadstate(" ".join(command[1:]).strip('"'))
            elif command[0] == "quit": quit()
            else: print("unrecognized command")

    size = 4 - 2*Mode
    addr = registers[15]-size
    addr -= addr & size-1
    if addr in Breakpoints:
        Pause = True
        Show = True
        print("Hit Breakpoint:")
    instr = mem_read(addr,size)
    if Mode and instr >= 0xF000:
        size = 4
        instr = mem_read(addr,size)
    execute(registers,instr,Mode)
    if mem_read(0x040000DF,1) & 2**7: DMA()

    if Show:
        print(f"{addr:0>8X}: {instr:0>{2*size}X}")
        showreg()