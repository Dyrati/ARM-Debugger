### November 17th, 2020
- added search function: Searches BIOS, RAM, and ROM
  - accepts integers, strings, and byte-like objects
  - for integers, can optionally specify a byte count
- spaces within quotation marks are no longer treated as separators
- fixed instructions that modify pc directly
- improved fbounds command, and added fboundsa for arm function boundaries
- added "nn" command, which is like "n", but doesn't step into functions
- modified "c" command; now you can specify an address to stop at
- regular breakpoints now halt prior to execution


### April 13th, 2020

- Fixed Overflow Flag calculation bug
- Modified error handling of Assembler
- Made assign not break with "=" sign in string
- Removed replacement of x with 0x
- Added ability to read/write BIOS
- Swapped replacement order in expstr_compile
- Added -out parameter to asm command, to store bytes of instructions
- Reworked strings to accept single quotes and escape sequences
- Added multi-byte disasm commands
- Made m command's 2nd argument be bytecount instead of element count
- Changed default arguments of m command
- Fixed "FileNotFound" error for default outputs
- Added option to display function with fbounds command


### April 6th, 2020

- pre-compiled expstr and assign functions
- fixed bitmask error with bl and blh instructions
- added ability to store strings, can now use byte strings
- changed concatenation operator to ".."
- modified exec mode to make error messages nicer
- added comtype3 for functions that don't split args
- fixed assignment to m(...) types
- added &=, |=, ^=, %= to MatchAssign
- can now use iterators instead of reversed lists in commandque
- made assembler match letters instead of non-spaces
- improved code in com_asm
- separated terminal command from output command
- assembly commands now accept // and () line comments
- fixed assembler bug mistaking "add rn, 13/15" for "add rn, sp/pc"
- added assembler error message
- added fbounds command
- added disasm command
- capitalized addresses in disassembler
- added custom print and input functions for terminal binding
- can now specify default folders
- improved file system error messages
- added dir, getcwd, and chdir os commands
- Completely rewrote assembler, eliminating reliance on eval();
  - now has more than twice as many lines of code, but is 3 times faster
- made disassembler ignore 0xb600-0xbbff range
