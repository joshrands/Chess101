load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "tools",
    srcs = glob(["*.py"]),
    imports = [".."],
    visibility = ["//visibility:public"],
    deps = [
        "//network:network",
        "@pip//numpy",
        "@pip//opencv_python",
    ],
)
