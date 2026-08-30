#!/bin/sh
# GTK4 cairo renderer (see /etc/xdg/labwc/env)
export GSK_RENDERER=cairo
# GTK 4.18: the accessibility (AT-SPI) context machinery has an infinite
# recursion crash (stack overflow in libgtk-4) with list/selection widgets
# when no a11y bus is present. GTK itself recommends GTK_A11Y=none here.
# Screen-reader users: set GTK_A11Y=atk-bridge to re-enable a11y.
GTK_A11Y=none
NO_AT_BRIDGE=1
export NO_AT_BRIDGE
export GTK_A11Y
