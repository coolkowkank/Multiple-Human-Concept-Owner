import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from src.app import add
assert add(2, 3) == 5
print('ok')
