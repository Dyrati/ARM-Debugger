# ARM Debugger
An easy to use, powerful debugger.  Import a rom, and an sgm file, and set breakpoints, watchpoints, and readpoints, view/modify registers and memory, output results to a txt file, and disassemble the code.

## Set Up
Make sure you have Python installed, and download the Debugger folder.  You can then open "Debugger.py", and that's it!
From there, you can type in help or ? to get detailed info on the available commands.
You can also start Debugger.py from the command line with two optional arguments: `[filepath to rom] [filepath to savestate]`

## Variables
You can store variables by typing in [identifier] = [expression]
```
> test = 12345
```
Then you can use those variables in place of any arguments.  Default variables are r0-r16, which refer to the registers (r16 is the psr), sp/lr/pc (r13-r15), and m(addr,size), which reads *size* bytes at *addr* (size=4 by default).

You can also use mathematical expressions including user variables as arguments.  If the command takes multiple arguments, then each mathematical expression must not contain spaces.
```
> chardata = $02000520
> m chardata+$14C*4 10
02000A50:  696C6546 00000078 00000000 05000000   Felix...........
02000A60:  00220046 3ACF4000 000C0020 0102001A   F."..@.: .......
02000A70:  00000000 0077006D                     ....m.w.
```
Hexadecimal numbers must be preceded by "0x", "$", or "x"

## Output
The output file is "output.txt"
Output is off by default.  By using the command `output true`, the registers and other data will be written to the file after each executed instruction.  You can pick a format using the `format` command.
