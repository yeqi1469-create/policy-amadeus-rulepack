"""Manual-maintenance desktop entry point; no automatic update services."""
import sys


def main():
    if any(arg.startswith('--auto-') or arg=='--review-health' for arg in sys.argv[1:]):
        return
    from policy_studio import PolicyStudio
    PolicyStudio().mainloop()


if __name__=='__main__':
    main()
