import sys

print(f'\n\n\n\n\nsys.path before fupi import:\n{"-"*50}')
print('\n'.join(sys.path))

import fupi

print(f'\n\nsys.path after fupi import:\n{"-"*50}')
print('\n'.join(sys.path))

print('\nShortest Path actively loaded by fupi:', fupi.shortest_path)
