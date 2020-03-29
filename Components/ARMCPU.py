from bisect import bisect_right


RAM, ROM = bytearray(), bytearray()
REG = [0]*17
RegionMarkers = {}
BreakState = ""
BreakPoints = set()
WatchPoints = set()
ReadPoints = set()
Conditionals = []
Executing = False


def undef(*args): pass


def mem_read(addr,size=4,signed=False):
    region = addr >> 24 & 0xF
    if region >= 8:
        reladdr = addr - 0x08000000
        value = int.from_bytes(ROM[reladdr:reladdr+size],"little")
    elif region not in RegionMarkers: return 0
    else:
        base, length = RegionMarkers[region]
        reladdr = (addr & 0xFFFFFF) % length + base
        value = int.from_bytes(RAM[reladdr:reladdr + size],"little")
    if signed:
        msb = 2**(8*size-1)
        value = ((value^msb) - msb) & 0xFFFFFFFF
    if addr in ReadPoints and Executing:
        global BreakState
        BreakState = f"ReadPoint: ${addr:0>{2*size}X} (={value:0>{2*size}X})"
    return value


def mem_write(addr,data,size=4):
    region = addr >> 24 & 0xF
    if region not in RegionMarkers: return 0
    if type(data) is int: data = int.to_bytes(data % 2**(8*size),size,"little")
    else: size = len(data)
    if addr in WatchPoints and Executing:
        global BreakState
        old, new = mem_read(addr,size), int.from_bytes(data, "little")
        BreakState = f"WatchPoint: {addr:0>8X} ({old:0>{2*size}X} -> {new:0>{2*size}X})"
    if region in RegionMarkers:
        base, length = RegionMarkers[region]
        reladdr = (addr & 0xFFFFFF) % length + base
        RAM[reladdr:reladdr+size] = data
    elif region >= 8:
        reladdr = addr - 0x08000000
        ROM[reladdr:reladdr+size] = data
    if RAM[RegionMarkers[4][0] + 0xDF] & 2**7: DMA()


def mem_copy(src,des,size):
    region1 = src >> 24 & 0xF
    region2 = des >> 24 & 0xF
    if region1 >= 8:
        reladdr = src - 0x08000000
        copydata = ROM[reladdr:reladdr + size]
    else:
        base, length = RegionMarkers[region1]
        reladdr = (src & 0xFFFFFF) % length + base
        copydata = RAM[reladdr:reladdr + size]
    try:
        base, length = RegionMarkers[region2]
        reladdr = (des & 0xFFFFFF) % length + base
        RAM[reladdr:reladdr+size] = copydata
    except KeyError:
        reladdr = des - 0x08000000
        ROM[reladdr:reladdr+size] = copydata


def DMA():
    src = mem_read(0x040000D4,4)
    des = mem_read(0x040000D8,4)
    count = mem_read(0x040000DC,2)
    control = mem_read(0x040000DE,2)
    mem_copy(src, des, count*(2 + 2*(control >> 10 & 1)))
    mem_write(0x040000DE, control & 0x7FFF, 2)


def compare(Op1,Op2,S=1):
    result = (Op1 & 0xFFFFFFFF) + (Op2 & 0xFFFFFFFF)
    sign1 = Op1 >> 30
    sign2 = Op2 >> 30
    N = 8 if result & 2**31 else 0
    Z = 4 if not result & 0xFFFFFFFF else 0
    C = 2 if result & 2**32 else 0
    V = 1 if sign1 == sign2 != N else 0
    if S: REG[16] = (N|Z|C|V) << 28 | REG[16] & 2**28-1
    return result & 0xFFFFFFFF


def cmphalf(result,S=1):
    result &= 0xFFFFFFFF
    N = 8 if result & 2**31 else 0
    Z = 4 if not result else 0
    if S: REG[16] = (N|Z) << 28 | REG[16] & 2**30-1
    return result


def barrelshift(value,Shift,Typ,S=0):
    value &= 0xFFFFFFFF
    Shift &= 31
    affectedflags = 0xE << 28
    if Shift: 
        C = 2*min(1, value & 1 << Shift-1)
        if Typ == 0: value <<= Shift; C = value >> 32 & 1
        elif Typ == 1: value >>= Shift
        elif Typ == 2: value = (value ^ 2**31) - 2**31 >> Shift
        elif Typ == 3: value = (value << 32 | value) >> Shift
    else:
        C = 2*(value>>31)
        if Typ == 0: affectedflags = 0xC << 28; C = 0
        elif Typ == 1: value = 0
        elif Typ == 2: value = -(value>>31)
        elif Typ == 3: value = ((REG[16] & 1<<29) << 3 | value) >> 1
    value &= 0xFFFFFFFF
    N = 8 if value & 2**31 else 0
    Z = 4 if not value else 0
    if S: REG[16] = REG[16] & ~affectedflags | (N|Z|C) << 28
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


#######################
### THUMB FUNCTIONS ###
#######################


def shifted(instr):
    Op,Offset,Rs,Rd = instr>>11 & 3, instr>>6 & 31, instr>>3 & 7, instr & 7
    REG[Rd] = barrelshift(REG[Rs],Offset,Op,1)


def addsub(instr):
    I,Op,Rn,Rs,Rd = instr>>10 & 1, instr>>9 & 1, instr>>6 & 7, instr>>3 & 7, instr & 7
    Rs = REG[Rs]
    if not I: Rn = REG[Rn]
    if not Op: REG[Rd] = compare(Rs,Rn)
    else: REG[Rd] = compare(Rs,-Rn)
    

def immediate(instr):
    Op,Rd,Offset = instr>>11 & 3, instr>>8 & 7, instr & 0xFF
    Op1 = REG[Rd]
    if Op == 0: REG[Rd] = cmphalf(Offset)
    elif Op == 1: compare(REG[Rd], -Offset)
    elif Op == 2: REG[Rd] = compare(REG[Rd], Offset)
    elif Op == 3: REG[Rd] = compare(REG[Rd],-Offset)


alu_ops = (
    lambda Rd,Rs: cmphalf(Rd & Rs),                        # AND
    lambda Rd,Rs: cmphalf(Rd ^ Rs),                        # XOR
    lambda Rd,Rs: barrelshift(Rd,Rs & 0x1F,0,1),           # LSL
    lambda Rd,Rs: barrelshift(Rd,Rs & 0x1F,1,1),           # LSR
    lambda Rd,Rs: barrelshift(Rd,Rs & 0x1F,2,1),           # ASR
    lambda Rd,Rs: compare(Rd, Rs + (REG[16]>>29 & 1)),     # ADC
    lambda Rd,Rs: compare(Rd,-Rs + (REG[16]>>29 & 1) - 1), # SBC
    lambda Rd,Rs: barrelshift(Rd,Rs & 0x1F,3,1),           # ROR
    lambda Rd,Rs: cmphalf(Rd & Rs),                        # TST
    lambda Rd,Rs: compare(0,-Rs),                          # NEG
    lambda Rd,Rs: compare(Rd,-Rs),                         # CMP
    lambda Rd,Rs: compare(Rd, Rs),                         # CMN
    lambda Rd,Rs: cmphalf(Rd | Rs),                        # ORR
    lambda Rd,Rs: cmphalf(Rd * Rs),                        # MUL
    lambda Rd,Rs: cmphalf(Rd & ~Rs),                       # BIC
    lambda Rd,Rs: cmphalf(~Rs),                            # MVN
)

def AluOp(instr):
    Op,Rs,Rd = instr>>6 & 15, instr>>3 & 7, instr & 7
    result = alu_ops[Op](REG[Rd],REG[Rs])
    if Op not in {8,10,11}: REG[Rd] = result


def HiRegBx(instr):
    Op,Hd,Hs,Rs,Rd = instr>>8 & 3, instr>>7 & 1, instr>>6 & 1, instr>>3 & 7, instr & 7
    Rd += 8*Hd
    Rs += 8*Hs
    if Op == 0: REG[Rd] = (REG[Rd] + REG[Rs]) & 0xFFFFFFFF
    elif Op == 1: compare(REG[Rd],-REG[Rs])
    elif Op == 2: REG[Rd] = REG[Rs]
    elif Op == 3:
        Mode = REG[Rs] & 1
        if Hd: REG[14] = REG[15] + 1
        REG[15] = REG[Rs] + 4-3*Mode
        REG[16] = REG[16] & ~(1<<5) | Mode << 5


def ldr_pc(instr):
    Rd,Word = instr>>8 & 7, instr & 0xFF
    REG[Rd] = mem_read(REG[15] + Word*4 - (REG[15] & 2), 4)


def ldrstr(instr):
    Op,S,Ro,Rb,Rd = instr>>10 & 3, instr>>9 & 1, instr>>6 & 7, instr>>3 & 7, instr & 7
    addr = REG[Rb] + REG[Ro]
    if not S:
        if Op == 0: mem_write(addr, REG[Rd], 4)
        elif Op == 1: mem_write(addr, REG[Rd], 1)
        elif Op == 2: REG[Rd] = mem_read(addr, 4)
        elif Op == 3: REG[Rd] = mem_read(addr, 1)
    else:
        if Op == 0: mem_write(addr, REG[Rd], 2)
        elif Op == 1: REG[Rd] = mem_read(addr, 1, True)
        elif Op == 2: REG[Rd] = mem_read(addr, 2)
        elif Op == 3: REG[Rd] = mem_read(addr, 2, True)


def ldrstr_imm(instr):
    Op,L,Offset,Rb,Rd = instr>>12 & 3, instr>>11 & 1, instr>>6 & 31, instr>>3 & 7, instr & 7
    size = Op^2 if Op != 2 else 4  # (3,2,0) -> (1,4,2)
    addr = REG[Rb] + Offset*size
    if not L: mem_write(addr, REG[Rd], size)
    else: REG[Rd] = mem_read(addr, size)


def ldrstr_sp(instr):
    Op,Rd,Word = instr>>11 & 1, instr>>8 & 7, instr & 0xFF
    if not Op: mem_write(REG[13] + Word*4, REG[Rd], 4)
    else: REG[Rd] = mem_read(REG[13] + Word*4, 4)


def get_reladdr(instr):
    Op,Rd,Word = instr>>11 & 1, instr>>8 & 7, instr & 0xFF
    if not Op: REG[Rd] = (REG[15] & ~2) + Word*4
    else: REG[Rd] = REG[13] + Word*4
    REG[Rd] &= 0xFFFFFFFF


def add_sp(instr):
    S,Word = instr>>7 & 1, instr & 0x7F
    if not S: REG[13] += Word*4
    else: REG[13] -= Word*4
    REG[13] &= 0xFFFFFFFF


def pushpop(instr):
    Op,Rlist = instr>>11 & 1, instr & 0x1FF
    Rlist = [i for i in range(9) if Rlist & 2**i]
    if Rlist[-1] == 8: Rlist[-1] = 14 + Op
    if not Op:
        for i in reversed(Rlist):
            REG[13] -= 4
            mem_write(REG[13], REG[i], 4)
    else:
        for i in Rlist:
            REG[i] = mem_read(REG[13], 4)
            REG[13] += 4
        if REG[15] & 1: REG[15] += 1
    REG[13] &= 0xFFFFFFFF


def stmldm(instr):
    Op,Rb,Rlist = instr>>11 & 1, instr>>8 & 7, instr & 0xFF
    addr = REG[Rb]
    for i in range(8):
        if Rlist & 2**i:
            if not Op: mem_write(addr, REG[i], 4)
            else: REG[i] = mem_read(addr, 4)
            addr += 4
    REG[Rb] = addr & 0xFFFFFFFF


def b_if(instr):
    Cond,Offset = instr>>8 & 15, instr & 0xFF
    if conditions[Cond](REG[16]>>28): 
        REG[15] = (REG[15] + ((Offset^0x80) - 0x80)*2 + 2) & 0xFFFFFFFF


def branch(instr):
    REG[15] = (REG[15] + ((instr & 0x7FF ^ 0x400) - 0x400)*2 + 2) & 0xFFFFFFFF


def bl(instr):
    if instr == 0xF800:
        link = REG[15] - 1
        REG[15] = REG[14] + 2
        REG[14] = link
    else:
        REG[14] = REG[15] + 1
        REG[15] = (REG[15] + (((instr & 0x7FF ^ 0x400) << 11 | (instr >> 16) & 0x7FF) - 0x200000)*2 + 2) & 0xFFFFFFFF


ThumbBounds = (
    0x1800,0x2000,0x4000,0x4400,0x4800,0x5000,0x6000,0x8000,0x9000,0xA000,
    0xB000,0xB400,0xBE00,0xC000,0xD000,0xDE00,0xDF00,0xE000,0xE800,0xF000,
)

ThumbFuncs = (
    shifted, addsub, immediate, AluOp, HiRegBx, ldr_pc, ldrstr, ldrstr_imm, ldrstr_imm, ldrstr_sp,
    get_reladdr, add_sp, pushpop, undef, stmldm, b_if, undef, undef, branch, undef, bl
)



#####################
### ARM FUNCTIONS ###
#####################


dataprocess_list = (
    lambda Rn,Op2,S: cmphalf(Rn & Op2, S),                         # AND
    lambda Rn,Op2,S: cmphalf(Rn ^ Op2, S),                         # EOR
    lambda Rn,Op2,S: compare(Rn, -Op2, S),                         # SUB
    lambda Rn,Op2,S: compare(Op2, -Rn, S),                         # RSB
    lambda Rn,Op2,S: compare(Rn, Op2, S),                          # ADD
    lambda Rn,Op2,S: compare(Rn, Op2 + (REG[16]>>29 & 1), S),      # ADC
    lambda Rn,Op2,S: compare(Rn,-Op2 + (REG[16]>>29 & 1) - 1, S),  # SBC
    lambda Rn,Op2,S: compare(Op2,-Rn + (REG[16]>>29 & 1) - 1, S),  # RSC
    lambda Rn,Op2,S: cmphalf(Rn & Op2, S),                         # TST
    lambda Rn,Op2,S: cmphalf(Rn ^ Op2, S),                         # TEQ
    lambda Rn,Op2,S: compare(Rn, -Op2, S),                         # CMP
    lambda Rn,Op2,S: compare(Rn, Op2, S),                          # CMN
    lambda Rn,Op2,S: cmphalf(Rn | Op2, S),                         # ORR
    lambda Rn,Op2,S: cmphalf(Op2, S),                              # MOV
    lambda Rn,Op2,S: cmphalf(Rn & ~Op2, S),                        # BIC
    lambda Rn,Op2,S: cmphalf(~Op2, S),                             # MVN
)


def dataprocess(instr):
    i = instr
    Imm, OpCode, S, Rn, Rd, Shift, Typ, Imm2, Rm = (
        i>>25 & 1, i>>21 & 15, i>>20 & 1, i>>16 & 15, i>>12 & 15, i>>7 & 31, i>>5 & 3, i>>4 & 1, i & 15)
    if Imm:
        Op2 = i & 0xFF
        Shift = (i >> 8 & 15)*2
        Op2 = ((Op2 & 2**Shift-1) << 32 | Op2) >> Shift
    else:
        if Imm2: Shift = REG[Shift>>1 & 15]
        Op2 = barrelshift(REG[Rm],Shift,Typ,S)
    result = dataprocess_list[OpCode](REG[Rn],Op2,S)
    if not(8 <= OpCode <= 11): REG[Rd] = result


def psr(instr):
    i = instr
    I, P, L, Field, Rd, Shift, Imm, Rm = (
        i>>25 & 1, i>>22 & 1, i>>21 & 1, i>>16 & 15, i>>12 & 15, i>>8 & 15, i & 0xFF, i & 15)
    if not P:
        if L:
            bitmask = 15<<28*(Field>>3) | 0xEF*(Field & 1)
            if I: Op = barrelshift(Imm, Shift*2, 3)
            else: Op = REG[Rm]
            REG[16] = REG[16] & ~bitmask | Op & bitmask
        else: R[Rd] = R[16]


def arm_bx(instr):
    L, Rn = instr >> 5 & 1, instr & 15
    if L: REG[14] = REG[15] - 4
    Mode = REG[Rn] & 1
    REG[15] = REG[Rn] + 4-3*Mode
    REG[16] = REG[16] & ~(1<<5) | Mode << 5


def arm_branch(instr):
    L, Offset = instr >> 24 & 1, instr & 0xFFFFFF
    if L: REG[14] = REG[15] - 4
    REG[15] = (REG[15] + 4 + Offset*4) & 0XFFFFFFFF


def clz(instr):
    Rd,Rm = instr >> 12 & 15, instr & 15    
    REG[Rd] = 32 - int.bit_length(REG[Rm])


def multiply(instr):
    i = instr
    OpCode, S, Rd, Rn, Rs, y, x, Rm = (i>>21 & 15, i>>20 & 1, i>>16 & 15, i>>12 & 15, i>>8 & 15, i>>6 & 1, i>>5 & 1, i & 15)
    Rm, Rs = REG[Rm], REG[Rs]
    if OpCode & 8:  #half registers
        OpCode &= 3
        S = 0
        Rs = (Rs >> 16*y & 0xFFFF ^ 2**15) - 2**15
        if OpCode != 1: Rm = (Rm >> 16*x & 0xFFFF ^ 2**15) - 2**15
        if OpCode == 0: REG[Rd] = (Rm*Rs + REG[Rn]) & 0xFFFFFFFF
        elif OpCode == 1: 
            Rm = (Rm ^ 2**31) - 2**31
            REG[Rd] = ((Rm*Rs >> 16) + REG[Rn]*(1-x)) & 0xFFFFFFFF
        elif OpCode == 2:
            result = (REG[Rd] << 32 | REG[Rn]) + Rm*Rs
            REG[Rd] = result >> 32 & 0xFFFFFFFF
            REG[Rn] = result & 0xFFFFFFFF
        elif OpCode == 3:
            REG[Rd] = Rm*Rs & 0xFFFFFFFF
    else:
        if OpCode & 2:  #signed
            Rm = (Rm ^ 2**31) - 2**31
            Rs = (Rs ^ 2**31) - 2**31
        result = Rm*Rs + REG[Rn]*(OpCode & 1)
        if OpCode & 4: 
            REG[Rd] = result >> 32 & 0xFFFFFFFF
            REG[Rn] = result & 0xFFFFFFFF
        else: 
            REG[Rd] = result & 0xFFFFFFFF
        if S:
            N = 8 if result & 2**63 else 0
            Z = 4 if not result & 2**63-1 else 0
            REG[16] = (N|Z)<<28 | (REG[16] & 2**30-1)


def datatransfer(instr):
    Flags, Rn, Rd, Offset = (instr>>20 & 0x7F, instr>>16 & 15, instr>>12 & 15, instr & 0xFFF)
    #Flags: Single/Double, Immediate offset, Pre/Post index, Up/Down, Byte/Int, Writeback, Load/Store
    D,I,P,U,B,W,L = (1 if Flags & 2**(6-i) else 0 for i in range(7))
    Shift, Typ, Rm = Offset>>7 & 31, Offset>>5 & 3, Offset & 15
    U = (-1,1)[U]
    addr = REG[Rn]
    if D:
        if I: Offset = barrelshift(REG[Rm],Shift,Typ)
        if P: addr += Offset*U
        if not P or W: REG[Rn] = (REG[Rn] + Offset*U) & 0xFFFFFFFF
        if L: REG[Rd] = mem_read(addr, 4 - 3*B)
        else: mem_write(addr, REG[Rd], 4 - 3*B)
    else:
        Rm = Offset & 15
        # B is Immediate offset flag when D is set
        if B: Offset = (Offset >> 8 & 15) << 4 | Offset & 15
        else: Offset = REG[Rm]
        if P: addr += Offset*U
        if not P or W: REG[Rn] = (REG[Rn] + Offset*U) & 0xFFFFFFFF
        if Typ == 0:
            temp = REG[Rm]  # in case Rm == Rd
            REG[Rd] = mem_read(REG[Rn],2-B)
            mem_write(REG[Rn],temp,2-B)
        elif L:
            if Typ == 1: REG[Rd] = mem_read(addr,2)
            elif Typ == 2: REG[Rd] = mem_read(addr, 1, True)
            elif Typ == 3: REG[Rd] = mem_read(addr, 2, True)
        else:
            if Typ == 1: mem_write(addr,REG[Rd],2)
            elif Typ == 2: REG[Rd],REG[Rd+1] = mem_read(addr,4), mem_read(addr + 4,4)
            elif Typ == 3: mem_write(addr,REG[Rd],4); mem_write(addr + 4,REG[Rd+1],4)


def blocktransfer(instr):
    Flags,Rn,Rlist = instr>>20 & 31, instr>>16 & 15, instr & 0xFFFF
    #Flags: Pre/Post, Up/Down, Load PSR, Writeback, Load/Store
    P,U,S,W,L = (1 if Flags & 2**(4-i) else 0 for i in range(5))
    direction = (-1,1)[U]
    addr = REG[Rn]
    if P: addr += 4*direction
    index = (15,0)[U]
    for i in range(16):
        if Rlist & 1<<index:
            if L: REG[index] = mem_read(addr,4)
            else: mem_write(addr, REG[index],4)
            addr += 4*direction
        index += direction
    if P: addr -= 4*direction
    if W: REG[Rn] = addr


arm_tree = {
    0:(27,36), 1:(26,31), 2:(25,28), 3:(4,9), 4:([25<<20,16<<20],6), 5:dataprocess, 6:(7,8), 7:psr, 
    8:multiply, 9:(7,19), 10:([25<<20,16<<20],12), 11:dataprocess, 12:(6,16), 13:(22,15), 14:arm_bx, 15:clz, 
    16:(5,18), 17:undef, 18:undef, 19:([3<<5,0],23), 20:(22,22), 21:datatransfer, 22:datatransfer, 23:(24,27), 
    24:(23,26), 25:multiply, 26:multiply, 27:datatransfer, 28:([25<<20,16<<20],30), 29:dataprocess, 30:psr, 31:(25,33), 
    32:datatransfer, 33:(4,35), 34:datatransfer, 35:undef, 36:(26,40), 37:(25,39), 38:blocktransfer, 39:arm_branch,
    40:(25,44), 41:([15<<21,2<<21],43), 42:undef, 43:undef, 44:(24,48), 45:(4,47), 46:undef, 47:undef,
    48:undef
}


def navigateTree(instr,tree):
    treepos = 0
    while True:
        try: 
            condition = tree[treepos][0]
            if type(condition) is int:
                if instr>>condition & 1: treepos = tree[treepos][1]
                else: treepos += 1
            else:
                bitmask,value = condition
                if instr & bitmask == value: treepos = tree[treepos][1]
                else: treepos += 1
        except TypeError:
            return tree[treepos]


def execute(instr,mode):
    global BreakState, Executing
    BreakState = ""
    Executing = True
    # THUMB
    if mode:
        REG[15] += 2
        ID = bisect_right(ThumbBounds,instr)
        ThumbFuncs[ID](instr)
    # ARM
    else:
        REG[15] += 4
        Cond = instr >> 28
        if conditions[Cond](REG[16]>>28):
            arm_function = navigateTree(instr,arm_tree)
            arm_function(instr)
    Executing = False