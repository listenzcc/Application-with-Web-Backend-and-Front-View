"""
File: test.py
Author: Chuncheng Zhang
Date: 2025-12-02
Copyright & Email: chuncheng.zhang@ia.ac.cn

Purpose:
    Test page for my Big CongMing ideas.

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
    4. Pending
    5. Pending
"""


# %% ---- 2025-12-02 ------------------------
# Requirements and constants
from nicegui import ui
from uuid import uuid4

# %% ---- 2025-12-02 ------------------------
# Function and class


def root():
    ui.label(f'This ID {str(uuid4())[:6]} changes only on reload.')
    ui.separator()
    ui.sub_pages({'/': main, '/other': other})


def main():
    ui.label('Main page content')
    ui.link('Go to other page', '/other')


def other():
    ui.label('Another page content')
    ui.link('Go to main page', '/')


ui.run(root)


# %% ---- 2025-12-02 ------------------------
# Play ground
# ui.label('Hello My Project!')

ui.run(root)
# ui.run()


# %% ---- 2025-12-02 ------------------------
# Pending


# %% ---- 2025-12-02 ------------------------
# Pending
