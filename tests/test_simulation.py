"""
Comprehensive Unit Tests for the pure-software IEC 61131-3 Structured Text Simulation Engine.
"""
import pytest
from src.simulation.simulator import STSimulator, SimulationError
from src.simulation.function_blocks import TON, TOF, TP, CTU, CTD, CTUD

def test_simulator_basic_expressions():
    code = """
    VAR
        a : INT := 10;
        b : INT := 3;
        sum : INT;
        diff : INT;
        prod : INT;
        quot : REAL;
        mod_val : INT;
        pwr : INT;
        b1 : BOOL := TRUE;
        b2 : BOOL := FALSE;
        bAnd : BOOL;
        bOr : BOOL;
        bXor : BOOL;
        bNot : BOOL;
    END_VAR

    sum := a + b;
    diff := a - b;
    prod := a * b;
    quot := a / b;
    mod_val := a MOD b;
    pwr := b ** 2;

    bAnd := b1 AND b2;
    bOr := b1 OR b2;
    bXor := b1 XOR b2;
    bNot := NOT b1;
    """
    sim = STSimulator()
    sim.load_program(code)
    sim.step()

    assert sim.get_variable("sum") == 13
    assert sim.get_variable("diff") == 7
    assert sim.get_variable("prod") == 30
    assert pytest.approx(sim.get_variable("quot"), 0.01) == 3.333
    assert sim.get_variable("mod_val") == 1
    assert sim.get_variable("pwr") == 9

    assert sim.get_variable("bAnd") is False
    assert sim.get_variable("bOr") is True
    assert sim.get_variable("bXor") is True
    assert sim.get_variable("bNot") is False

def test_simulator_standard_functions():
    code = """
    VAR
        val : REAL := -25.0;
        abs_v : REAL;
        sqrt_v : REAL;
        min_v : INT;
        max_v : INT;
        lim_v : INT;
        sel_v : INT;
    END_VAR

    abs_v := ABS(val);
    sqrt_v := SQRT(abs_v);
    min_v := MIN(10, 20);
    max_v := MAX(10, 20);
    lim_v := LIMIT(0, 150, 100);
    sel_v := SEL(TRUE, 10, 20);
    """
    sim = STSimulator()
    sim.load_program(code)
    sim.step()

    assert sim.get_variable("abs_v") == 25.0
    assert sim.get_variable("sqrt_v") == 5.0
    assert sim.get_variable("min_v") == 10
    assert sim.get_variable("max_v") == 20
    assert sim.get_variable("lim_v") == 100
    assert sim.get_variable("sel_v") == 20

def test_ton_timer():
    code = """
    PROGRAM TonTest
    VAR_INPUT
        bStart : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        bDone : BOOL := FALSE;
        tElapsed : TIME := 0.0;
    END_VAR
    VAR
        myTimer : TON;
    END_VAR

    myTimer(IN := bStart, PT := T#50ms);
    bDone := myTimer.Q;
    tElapsed := myTimer.ET;
    END_PROGRAM
    """
    sim = STSimulator(default_dt_ms=10.0)
    sim.load_program(code)

    # 1. Start false -> Q false, ET 0
    sim.step()
    assert sim.get_variable("bDone") is False
    assert sim.get_variable("tElapsed") == 0.0

    # 2. Start true -> step 10ms, 20ms, 30ms, 40ms
    sim.set_variable("bStart", True)
    for expected_et in (10.0, 20.0, 30.0, 40.0):
        sim.step()
        assert sim.get_variable("bDone") is False
        assert sim.get_variable("tElapsed") == expected_et

    # 3. 50ms reached -> Q becomes True
    sim.step()
    assert sim.get_variable("bDone") is True
    assert sim.get_variable("tElapsed") == 50.0

    # 4. Remains True while bStart is True
    sim.step()
    assert sim.get_variable("bDone") is True

    # 5. bStart goes False -> resets Q to False and ET to 0
    sim.set_variable("bStart", False)
    sim.step()
    assert sim.get_variable("bDone") is False
    assert sim.get_variable("tElapsed") == 0.0

def test_tof_timer():
    code = """
    PROGRAM TofTest
    VAR_INPUT
        bIn : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        bOut : BOOL := FALSE;
        tElapsed : TIME := 0.0;
    END_VAR
    VAR
        timerOff : TOF;
    END_VAR

    timerOff(IN := bIn, PT := T#30ms);
    bOut := timerOff.Q;
    tElapsed := timerOff.ET;
    END_PROGRAM
    """
    sim = STSimulator(default_dt_ms=10.0)
    sim.load_program(code)

    # Initially false
    sim.step()
    assert sim.get_variable("bOut") is False

    # Turn ON
    sim.set_variable("bIn", True)
    sim.step()
    assert sim.get_variable("bOut") is True

    # Turn OFF -> falling edge starts 30ms off-delay timer
    sim.set_variable("bIn", False)
    sim.step()  # 10ms
    assert sim.get_variable("bOut") is True
    assert sim.get_variable("tElapsed") == 10.0

    sim.step()  # 20ms
    assert sim.get_variable("bOut") is True
    assert sim.get_variable("tElapsed") == 20.0

    sim.step()  # 30ms -> timer expires, Q falls to False
    assert sim.get_variable("bOut") is False
    assert sim.get_variable("tElapsed") == 30.0

def test_tp_pulse_timer():
    code = """
    PROGRAM TpTest
    VAR_INPUT
        bTrigger : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        bPulseOut : BOOL := FALSE;
    END_VAR
    VAR
        timerPulse : TP;
    END_VAR

    timerPulse(IN := bTrigger, PT := T#20ms);
    bPulseOut := timerPulse.Q;
    END_PROGRAM
    """
    sim = STSimulator(default_dt_ms=10.0)
    sim.load_program(code)

    # Trigger pulse (rising edge)
    sim.set_variable("bTrigger", True)
    sim.step()  # Cycle 1: pulse active (10ms)
    assert sim.get_variable("bPulseOut") is True

    # Cycle 2: reaches 20ms -> pulse ends
    sim.step()
    assert sim.get_variable("bPulseOut") is False

    # Falling edge resets
    sim.set_variable("bTrigger", False)
    sim.step()
    assert sim.get_variable("bPulseOut") is False

def test_ctu_counter():
    code = """
    PROGRAM CtuTest
    VAR_INPUT
        bCount : BOOL := FALSE;
        bRst : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        iVal : INT := 0;
        bDone : BOOL := FALSE;
    END_VAR
    VAR
        myCounter : CTU;
    END_VAR

    myCounter(CU := bCount, RESET := bRst, PV := 3);
    iVal := myCounter.CV;
    bDone := myCounter.Q;
    END_PROGRAM
    """
    sim = STSimulator()
    sim.load_program(code)

    # Initial state
    sim.step()
    assert sim.get_variable("iVal") == 0
    assert sim.get_variable("bDone") is False

    # Pulse 1
    sim.set_variable("bCount", True); sim.step()
    sim.set_variable("bCount", False); sim.step()
    assert sim.get_variable("iVal") == 1
    assert sim.get_variable("bDone") is False

    # Pulse 2
    sim.set_variable("bCount", True); sim.step()
    sim.set_variable("bCount", False); sim.step()
    assert sim.get_variable("iVal") == 2
    assert sim.get_variable("bDone") is False

    # Pulse 3 -> Reaches PV=3
    sim.set_variable("bCount", True); sim.step()
    assert sim.get_variable("iVal") == 3
    assert sim.get_variable("bDone") is True

    # Reset
    sim.set_variable("bRst", True); sim.step()
    assert sim.get_variable("iVal") == 0
    assert sim.get_variable("bDone") is False

def test_ctd_counter():
    code = """
    PROGRAM CtdTest
    VAR_INPUT
        bDown : BOOL := FALSE;
        bLd : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        iVal : INT := 0;
        bZero : BOOL := FALSE;
    END_VAR
    VAR
        downCounter : CTD;
    END_VAR

    downCounter(CD := bDown, LOAD := bLd, PV := 2);
    iVal := downCounter.CV;
    bZero := downCounter.Q;
    END_PROGRAM
    """
    sim = STSimulator()
    sim.load_program(code)

    # Load PV=2
    sim.set_variable("bLd", True); sim.step()
    assert sim.get_variable("iVal") == 2
    assert sim.get_variable("bZero") is False

    # Count down 1
    sim.set_variable("bLd", False)
    sim.set_variable("bDown", True); sim.step()
    sim.set_variable("bDown", False); sim.step()
    assert sim.get_variable("iVal") == 1
    assert sim.get_variable("bZero") is False

    # Count down 2 (reaches 0)
    sim.set_variable("bDown", True); sim.step()
    assert sim.get_variable("iVal") == 0
    assert sim.get_variable("bZero") is True

def test_state_machine_flow():
    code = """
    PROGRAM StateMachine
    VAR
        state : INT := 0;
        alarm : BOOL := FALSE;
        speed : INT := 0;
    END_VAR

    CASE state OF
        0: // STOPPED
            speed := 0;
            alarm := FALSE;
            state := 1;
        1: // ACCELERATING
            speed := speed + 25;
            IF speed >= 100 THEN
                state := 2;
            END_IF;
        2: // RUNNING
            speed := 100;
            IF alarm THEN
                state := 3;
            END_IF;
        3: // EMERGENCY_STOP
            speed := 0;
    END_CASE;
    END_PROGRAM
    """
    sim = STSimulator()
    sim.load_program(code)

    # Cycle 1: state 0 -> transitions to 1
    sim.step()
    assert sim.get_variable("state") == 1

    # Accelerate 4 cycles: 25, 50, 75, 100 (transitions to state 2)
    sim.step(); assert sim.get_variable("speed") == 25
    sim.step(); assert sim.get_variable("speed") == 50
    sim.step(); assert sim.get_variable("speed") == 75
    sim.step(); assert sim.get_variable("speed") == 100
    assert sim.get_variable("state") == 2

    # Running steady state
    sim.step()
    assert sim.get_variable("state") == 2
    assert sim.get_variable("speed") == 100

    # Trigger alarm -> transitions to 3 in this cycle
    sim.set_variable("alarm", True)
    sim.step()
    assert sim.get_variable("state") == 3

    # Next cycle executes state 3 (EMERGENCY_STOP) logic
    sim.step()
    assert sim.get_variable("speed") == 0

def test_loops_and_exit():
    code = """
    VAR
        sum : INT := 0;
        i : INT := 0;
    END_VAR

    FOR i := 1 TO 10 BY 1 DO
        sum := sum + i;
        IF i = 5 THEN
            EXIT;
        END_IF;
    END_FOR;
    """
    sim = STSimulator()
    sim.load_program(code)
    sim.step()

    # Sum of 1+2+3+4+5 = 15
    assert sim.get_variable("sum") == 15

def test_array_operations():
    code = """
    VAR
        arr : ARRAY [1..5] OF INT;
        total : INT := 0;
    END_VAR

    arr[1] := 10;
    arr[2] := 20;
    arr[3] := 30;
    total := arr[1] + arr[2] + arr[3];
    """
    sim = STSimulator()
    sim.load_program(code)
    sim.step()

    assert sim.get_variable("total") == 60

def test_infinite_loop_protection():
    code = """
    VAR
        x : INT := 0;
    END_VAR
    WHILE TRUE DO
        x := x + 1;
    END_WHILE;
    """
    sim = STSimulator(max_loop_iterations=100)
    sim.load_program(code)
    with pytest.raises(SimulationError, match="Infinite loop detected"):
        sim.step()

def test_division_by_zero_error():
    code = """
    VAR
        x : INT := 10;
        y : INT := 0;
        z : REAL;
    END_VAR
    z := x / y;
    """
    sim = STSimulator()
    sim.load_program(code)
    with pytest.raises(SimulationError, match="Division by zero"):
        sim.step()

def test_ctud_counter():
    code = """
    PROGRAM CtudTest
    VAR_INPUT
        bUp : BOOL := FALSE;
        bDown : BOOL := FALSE;
        bRst : BOOL := FALSE;
        bLd : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        iVal : INT := 0;
        bQu : BOOL := FALSE;
        bQd : BOOL := FALSE;
    END_VAR
    VAR
        biCounter : CTUD;
    END_VAR

    biCounter(CU := bUp, CD := bDown, RESET := bRst, LOAD := bLd, PV := 2);
    iVal := biCounter.CV;
    bQu := biCounter.QU;
    bQd := biCounter.QD;
    END_PROGRAM
    """
    sim = STSimulator()
    sim.load_program(code)

    # Initial cycle
    sim.step()
    assert sim.get_variable("iVal") == 0
    assert sim.get_variable("bQu") is False
    assert sim.get_variable("bQd") is True

    # Count up 1
    sim.set_variable("bUp", True); sim.step()
    sim.set_variable("bUp", False); sim.step()
    assert sim.get_variable("iVal") == 1
    assert sim.get_variable("bQu") is False
    assert sim.get_variable("bQd") is False

    # Count up 2 (reaches PV=2)
    sim.set_variable("bUp", True); sim.step()
    assert sim.get_variable("iVal") == 2
    assert sim.get_variable("bQu") is True
    assert sim.get_variable("bQd") is False

    # Count down 1
    sim.set_variable("bUp", False)
    sim.set_variable("bDown", True); sim.step()
    sim.set_variable("bDown", False); sim.step()
    assert sim.get_variable("iVal") == 1
    assert sim.get_variable("bQu") is False
    assert sim.get_variable("bQd") is False

def test_direct_register_variables():
    """Verify STSimulator handles direct register identifiers like %I1, %Q1, %R1."""
    code = """
    PROGRAM DirectTest
    %Q1 := %I1;
    %R1 := 42;
    END_PROGRAM
    """
    sim = STSimulator()
    sim.load_program(code)
    sim.set_variable("%I1", True)
    sim.step()

    assert sim.get_variable("%Q1") is True
    assert sim.get_variable("%R1") == 42