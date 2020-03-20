ROM = bytearray()


def bl_offset(data):
    data = int.from_bytes(data,"little")
    return 2*(((data & 0x7FF ^ 0x400) << 11 | (data >> 16) & 0x7FF) - 0x200000 + 2)
    

def generateFuncList(addr, depth=0):
    
    """
    Arguments:
        addr    -- the starting point; integer relative to the base address of the rom
        depth   -- set to a number > 0 to limit the search depth
    """

    s = hex(addr)[2:].zfill(8)
    path = [s]
    currentFuncList = [set()]
    totalFuncList = set()
    currentBranchList = [set()]

    def navigate_tree(addr):
        nonlocal s
        newentry = ""
        stepinto = True
        endfunc = False

        while True:
            instr = int.from_bytes(ROM[addr:addr+2],"little")

            # b {conditional}; updates the local list of branches of the function
            if 0xD000 <= instr < 0xDE00:
                offset = 2*((instr&0xFF^0x80)-0x80) + 4
                if offset > 0: currentBranchList[-1].add(addr + offset)
                
            # b {unconditional}; branches to the smallest address in the local branch list that's greater than addr
            elif 0xE000 <= instr < 0xE800:
                offset = 2*((instr&0x7FF^0x400)-0x400) + 4
                if offset > 0:
                    currentBranchList[-1] = set(filter(lambda x: addr < x,currentBranchList[-1].union((addr + offset,))))
                    addr = min(currentBranchList[-1])
                    continue

            # bl instructions
            elif 0xF000 <= instr < 0xF800 and int.from_bytes(ROM[addr+2:addr+4],"little") >= 0xF800:
                newaddr = addr + bl_offset(ROM[addr:addr+4])
                newentry = f"08{hex(newaddr)[2:]:0>6}"
                addr += 2

            # bx instructions
            elif 0x4700 <= instr <= 0x4770:
                if instr <= 0x4738 and (instr & 0x38) >> 3 == ROM[addr-1] & 0x7:
                    newaddr = int.from_bytes(ROM[addr+2:addr+6],"little")
                    newentry = f"{hex(newaddr-(newaddr&1))[2:]:0>8}"
                    if not (newaddr & 1 and newaddr>>27 & 1): stepinto = False # if it's not thumb, don't step into it
                    newaddr &= 0xFFFFFE
                endfunc = True

            # pop {pc}
            elif instr>>8 == 0xBD: endfunc = True
            
            if newentry and newentry not in currentFuncList[-1]:
                currentFuncList[-1].add(newentry)
                if len(currentFuncList[-1]) > 1:
                    print(s)
                    s = f"{' '*(len(path)*13-3)}|- {newentry}"
                else: 
                    s += " --- " + newentry

                # step into the new function recursively
                if stepinto and (depth == 0 or depth > len(path)) and newentry not in totalFuncList:
                    totalFuncList.add(newentry)
                    currentFuncList.append(set())
                    currentBranchList.append(set())
                    path.append(newentry)
                    navigate_tree(newaddr)

            # return by exiting navigate_tree
            if endfunc:
                currentFuncList.pop()
                currentBranchList.pop()
                path.pop()
                break

            newentry = ""
            addr += 2

    navigate_tree(addr - 0x08000000)
    print(s)
