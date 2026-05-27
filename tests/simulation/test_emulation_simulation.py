import unittest

class TesteDBSimulation(unittest.TestCase):
    def test_nvram_crash_recovery_simulation(self):
        # Simulate NVRAM write-ahead logging (WAL) and recovery after power loss
        wal_log = ["set key_1 value_1", "set key_2 value_2"]
        db_state = {}
        # Power loss occurs here...
        # Reboot and recover from WAL
        for entry in wal_log:
            cmd, k, v = entry.split()
            db_state[k] = v
        assert db_state["key_1"] == "value_1", "NVRAM crash recovery simulation failed"
