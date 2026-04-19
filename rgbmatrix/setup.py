import os, sys
from distutils.core import setup, Extension

lib_dir = os.path.expanduser(os.environ.get("RGB_LIB_DIR", "~/rpi-rgb-led-matrix"))

setup(ext_modules=[
    Extension("core",     sources=["core.cpp"],     include_dirs=[f"{lib_dir}/include"], library_dirs=[f"{lib_dir}/lib"], libraries=["rgbmatrix"], extra_compile_args=["-std=c++11"], language="c++"),
    Extension("graphics", sources=["graphics.cpp"], include_dirs=[f"{lib_dir}/include"], library_dirs=[f"{lib_dir}/lib"], libraries=["rgbmatrix"], extra_compile_args=["-std=c++11"], language="c++"),
])
