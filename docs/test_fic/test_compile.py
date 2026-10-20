"""Проверить, почему compile() не принимает em-dash."""
src = '''# -*- coding: utf-8 -*-
# Тест — em-dash в комментарии
'''
try:
    compile(src, '<test>', 'exec')
    print('OK: em-dash accepted')
except SyntaxError as e:
    print(f'FAIL: {e}')

src2 = '''# Тест - простое тире в комментарии
'''
try:
    compile(src2, '<test>', 'exec')
    print('OK: dash accepted')
except SyntaxError as e:
    print(f'FAIL: {e}')