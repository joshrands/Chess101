load("@rules_python//python:defs.bzl", "py_library", "py_binary")

py_library(
    name = "hil",
    srcs = glob(["*.py"], exclude = ["run_hil.py"]),
    imports = [".."],
    visibility = ["//visibility:public"],
    deps = [
        "//core:core",
        "//hardware:hardware",
        "@pip//websockets",
    ],
)

py_binary(
    name = "run_hil",
    srcs = ["run_hil.py"],
    imports = [".."],
    visibility = ["//visibility:public"],
    deps = [
        ":hil",
        "//game:game",
    ],
)
