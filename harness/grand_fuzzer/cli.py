"""Unified CLI for grand fuzzer suite.

Usage:
    bazel run //harness:grand_fuzzer -- grand --iterations 100
    bazel run //harness:grand_fuzzer -- phase --iterations 100
    bazel run //harness:grand_fuzzer -- validator --iterations 100
    bazel run //harness:grand_fuzzer -- reconnect --iterations 100
    bazel run //harness:grand_fuzzer -- state_machine --iterations 100
    bazel run //harness:grand_fuzzer -- all --iterations 100
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def run_grand(args) -> int:
    """Run Grand E2E fuzzer."""
    from harness.grand_fuzzer.fuzzers.grand_e2e import GrandE2EFuzzer, SlaveMode
    from harness.grand_fuzzer.core.chaos import ChaosProfile

    mode_map = {
        "local": SlaveMode.LOCAL,
        "lan_host": SlaveMode.LAN_HOST,
        "lan_guest": SlaveMode.LAN_GUEST,
        "lan_beacon_host": SlaveMode.LAN_BEACON_HOST,
        "lan_beacon_guest": SlaveMode.LAN_BEACON_GUEST,
        "lan_mdns_host": SlaveMode.LAN_MDNS_HOST,
        "lan_mdns_guest": SlaveMode.LAN_MDNS_GUEST,
        "online_host": SlaveMode.ONLINE_HOST,
        "online_guest": SlaveMode.ONLINE_GUEST,
    }
    mode = mode_map.get(args.mode, SlaveMode.LOCAL)

    profile_map = {
        "gentle": ChaosProfile.GENTLE,
        "standard": ChaosProfile.STANDARD,
        "aggressive": ChaosProfile.AGGRESSIVE,
        "adversarial": ChaosProfile.ADVERSARIAL,
    }
    profile = profile_map.get(args.profile, ChaosProfile.STANDARD)

    enabled_scenarios = None
    if args.scenarios:
        if args.scenarios.lower() == "none":
            enabled_scenarios = set()  # Empty set = no scenarios
        else:
            enabled_scenarios = set(s.strip().upper() for s in args.scenarios.split(","))

    print(f"[grand_e2e] mode={args.mode} profile={args.profile} iterations={args.iterations} seed={args.seed}")
    fuzzer = GrandE2EFuzzer(
        seed=args.seed,
        mode=mode,
        hil_url=args.hil_url,
        relay_url=args.relay_url,
        lan_port=args.lan_port,
        chaos_profile=profile,
        enabled_scenarios=enabled_scenarios,
    )
    total, ok, failed = fuzzer.run_fuzzing(args.iterations)
    print(f"[grand_e2e] total={total} ok={ok} failed={failed}")
    return 1 if failed > 0 else 0


def run_phase(args) -> int:
    """Run phase fuzzer."""
    from harness.grand_fuzzer.fuzzers.phase_fuzzer import PhaseFuzzer

    print(f"[phase] iterations={args.iterations} seed={args.seed}")
    fuzzer = PhaseFuzzer(seed=args.seed)
    total, passed, failed = fuzzer.run_fuzzing(args.iterations)
    print(f"[phase] total={total} passed={passed} failed={failed}")
    return 1 if failed > 0 else 0


def run_validator(args) -> int:
    """Run validator fuzzer."""
    from harness.grand_fuzzer.fuzzers.validator_fuzzer import ValidatorFuzzer

    print(f"[validator] iterations={args.iterations} seed={args.seed}")
    fuzzer = ValidatorFuzzer(seed=args.seed)
    total, passed, failed = fuzzer.run_fuzzing(args.iterations)
    print(f"[validator] total={total} passed={passed} failed={failed}")
    return 1 if failed > 0 else 0


def run_reconnect(args) -> int:
    """Run reconnect fuzzer."""
    from harness.grand_fuzzer.fuzzers.reconnect_fuzzer import ReconnectFuzzer

    print(f"[reconnect] iterations={args.iterations} seed={args.seed}")
    fuzzer = ReconnectFuzzer(seed=args.seed)
    total, passed, failed = fuzzer.run_fuzzing(args.iterations)
    print(f"[reconnect] total={total} passed={passed} failed={failed}")
    return 1 if failed > 0 else 0


def run_state_machine(args) -> int:
    """Run state machine fuzzer."""
    from harness.grand_fuzzer.fuzzers.state_machine import StateMachineFuzzer

    print(f"[state_machine] iterations={args.iterations} seed={args.seed}")
    fuzzer = StateMachineFuzzer(seed=args.seed)
    total, passed, failed = fuzzer.run_fuzzing(args.iterations)
    print(f"[state_machine] total={total} passed={passed} failed={failed}")
    return 1 if failed > 0 else 0


def run_all(args) -> int:
    """Run all fuzzers."""
    total_failed = 0

    print("=== Running all fuzzers ===\n")

    print("--- Phase Fuzzer ---")
    total_failed += run_phase(args)

    print("\n--- Validator Fuzzer ---")
    total_failed += run_validator(args)

    print("\n--- Reconnect Fuzzer ---")
    total_failed += run_reconnect(args)

    print("\n--- State Machine Fuzzer ---")
    total_failed += run_state_machine(args)

    print("\n--- Grand E2E Fuzzer ---")
    total_failed += run_grand(args)

    print(f"\n=== All fuzzers complete. Total failures: {total_failed} ===")
    return 1 if total_failed > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grand Fuzzer Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  grand          Grand E2E lockstep fuzzer (network + engines)
  phase          Phase message fuzzer (COLOR_PICK, WAR_GAMES, SETUP)
  validator      Adversarial validator fuzzer
  reconnect      Reconnection edge case fuzzer
  state_machine  Game state machine fuzzer
  all            Run all fuzzers
        """,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common arguments
    def add_common_args(p):
        p.add_argument("--iterations", "-n", type=int, default=100)
        p.add_argument("--seed", "-s", type=int, default=42)

    # Grand E2E
    grand_parser = subparsers.add_parser("grand", help="Grand E2E lockstep fuzzer")
    add_common_args(grand_parser)
    grand_parser.add_argument(
        "--mode", "-m",
        choices=[
            "local",
            "lan_host", "lan_guest",
            "lan_beacon_host", "lan_beacon_guest",
            "lan_mdns_host", "lan_mdns_guest",
            "online_host", "online_guest",
        ],
        default="local",
    )
    grand_parser.add_argument("--hil-url", help="HIL server WebSocket URL")
    grand_parser.add_argument("--relay-url", default="wss://relay.chess101.net")
    grand_parser.add_argument("--lan-port", type=int, default=65101)
    grand_parser.add_argument(
        "--profile", "-p",
        choices=["gentle", "standard", "aggressive", "adversarial"],
        default="standard",
        help="Chaos intensity profile (default: standard)",
    )
    grand_parser.add_argument(
        "--scenarios",
        help="Comma-separated scenarios to enable",
    )
    grand_parser.set_defaults(func=run_grand)

    # Phase
    phase_parser = subparsers.add_parser("phase", help="Phase message fuzzer")
    add_common_args(phase_parser)
    phase_parser.set_defaults(func=run_phase)

    # Validator
    validator_parser = subparsers.add_parser("validator", help="Adversarial validator fuzzer")
    add_common_args(validator_parser)
    validator_parser.set_defaults(func=run_validator)

    # Reconnect
    reconnect_parser = subparsers.add_parser("reconnect", help="Reconnection fuzzer")
    add_common_args(reconnect_parser)
    reconnect_parser.set_defaults(func=run_reconnect)

    # State machine
    sm_parser = subparsers.add_parser("state_machine", help="State machine fuzzer")
    add_common_args(sm_parser)
    sm_parser.set_defaults(func=run_state_machine)

    # All
    all_parser = subparsers.add_parser("all", help="Run all fuzzers")
    add_common_args(all_parser)
    all_parser.add_argument("--mode", "-m", default="local")
    all_parser.add_argument("--hil-url", default=None)
    all_parser.add_argument("--relay-url", default="wss://relay.chess101.net")
    all_parser.add_argument("--lan-port", type=int, default=65101)
    all_parser.set_defaults(func=run_all)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
