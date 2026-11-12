import os

# Tests never call the network.
os.environ["CONTRACTGUARD_OFFLINE"] = "1"
