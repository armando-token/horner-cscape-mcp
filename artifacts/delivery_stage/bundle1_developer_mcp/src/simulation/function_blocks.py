"""
IEC 61131-3 Standard Function Blocks (Timers, Counters) and Standard Functions.
"""
import math
from typing import Dict, Any, Optional

class IECFunctionBlock:
    """Base class for all IEC 61131-3 Function Blocks."""
    def __init__(self, name: str = ""):
        self.name = name
        self.inputs: Dict[str, Any] = {}
        self.outputs: Dict[str, Any] = {}
        self.internal: Dict[str, Any] = {}

    def get_member(self, member: str) -> Any:
        m = member.upper()
        if m in self.outputs:
            return self.outputs[m]
        if m in self.inputs:
            return self.inputs[m]
        if m in self.internal:
            return self.internal[m]
        raise AttributeError(f"Function block '{self.name}' has no member '{member}'")

    def set_member(self, member: str, value: Any) -> None:
        m = member.upper()
        if m in self.inputs:
            self.inputs[m] = value
        elif m in self.outputs:
            self.outputs[m] = value
        else:
            self.internal[m] = value

    def reset(self) -> None:
        pass

    def execute(self, dt_ms: float = 0.0) -> None:
        pass

    def call(self, args: Optional[Dict[str, Any]] = None, dt_ms: float = 0.0) -> Dict[str, Any]:
        if args:
            for k, v in args.items():
                self.set_member(k, v)
        self.execute(dt_ms=dt_ms)
        return dict(self.outputs)

class TON(IECFunctionBlock):
    """
    IEC 61131-3 TON: On-Delay Timer.
    Inputs:
      IN: BOOL - Timer start condition
      PT: TIME (ms) - Preset time
    Outputs:
      Q: BOOL - Timer output (TRUE when ET >= PT)
      ET: TIME (ms) - Elapsed time
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.inputs = {"IN": False, "PT": 0.0}
        self.outputs = {"Q": False, "ET": 0.0}
        self.internal = {"running": False}

    def reset(self) -> None:
        self.inputs["IN"] = False
        self.outputs["Q"] = False
        self.outputs["ET"] = 0.0
        self.internal["running"] = False

    def execute(self, dt_ms: float = 0.0) -> None:
        in_sig = bool(self.inputs.get("IN", False))
        pt = float(self.inputs.get("PT", 0.0))

        if not in_sig:
            self.outputs["ET"] = 0.0
            self.outputs["Q"] = False
            self.internal["running"] = False
        else:
            if not self.internal["running"]:
                self.internal["running"] = True
                self.outputs["ET"] = 0.0

            cur_et = self.outputs["ET"] + dt_ms
            if pt <= 0.0:
                self.outputs["ET"] = 0.0
                self.outputs["Q"] = True
            elif cur_et >= pt:
                self.outputs["ET"] = pt
                self.outputs["Q"] = True
            else:
                self.outputs["ET"] = cur_et
                self.outputs["Q"] = False

class TOF(IECFunctionBlock):
    """
    IEC 61131-3 TOF: Off-Delay Timer.
    Inputs:
      IN: BOOL - Input signal
      PT: TIME (ms) - Preset delay time
    Outputs:
      Q: BOOL - Output signal (remains TRUE for PT after IN falls)
      ET: TIME (ms) - Elapsed time
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.inputs = {"IN": False, "PT": 0.0}
        self.outputs = {"Q": False, "ET": 0.0}
        self.internal = {"running": False, "prev_in": False}

    def reset(self) -> None:
        self.inputs["IN"] = False
        self.outputs["Q"] = False
        self.outputs["ET"] = 0.0
        self.internal["running"] = False
        self.internal["prev_in"] = False

    def execute(self, dt_ms: float = 0.0) -> None:
        in_sig = bool(self.inputs.get("IN", False))
        pt = float(self.inputs.get("PT", 0.0))
        prev_in = self.internal["prev_in"]

        if in_sig:
            self.outputs["Q"] = True
            self.outputs["ET"] = 0.0
            self.internal["running"] = False
        else:
            # Falling edge detected
            if prev_in and not in_sig:
                self.internal["running"] = True
                self.outputs["ET"] = 0.0
                self.outputs["Q"] = True

            if self.internal["running"]:
                cur_et = self.outputs["ET"] + dt_ms
                if cur_et >= pt:
                    self.outputs["ET"] = pt
                    self.outputs["Q"] = False
                    self.internal["running"] = False
                else:
                    self.outputs["ET"] = cur_et
                    self.outputs["Q"] = True
            else:
                self.outputs["Q"] = False
                self.outputs["ET"] = pt

        self.internal["prev_in"] = in_sig

class TP(IECFunctionBlock):
    """
    IEC 61131-3 TP: Pulse Timer.
    Inputs:
      IN: BOOL - Trigger input
      PT: TIME (ms) - Pulse width
    Outputs:
      Q: BOOL - Pulse output
      ET: TIME (ms) - Elapsed time
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.inputs = {"IN": False, "PT": 0.0}
        self.outputs = {"Q": False, "ET": 0.0}
        self.internal = {"running": False, "prev_in": False}

    def reset(self) -> None:
        self.inputs["IN"] = False
        self.outputs["Q"] = False
        self.outputs["ET"] = 0.0
        self.internal["running"] = False
        self.internal["prev_in"] = False

    def execute(self, dt_ms: float = 0.0) -> None:
        in_sig = bool(self.inputs.get("IN", False))
        pt = float(self.inputs.get("PT", 0.0))
        prev_in = self.internal["prev_in"]

        if not self.internal["running"]:
            # Check for rising edge
            if in_sig and not prev_in:
                self.internal["running"] = True
                self.outputs["Q"] = True
                self.outputs["ET"] = 0.0
            else:
                self.outputs["Q"] = False
                self.outputs["ET"] = 0.0

        if self.internal["running"]:
            cur_et = self.outputs["ET"] + dt_ms
            if cur_et >= pt:
                self.outputs["ET"] = pt
                self.outputs["Q"] = False
                if not in_sig:
                    self.internal["running"] = False
                    self.outputs["ET"] = 0.0
            else:
                self.outputs["ET"] = cur_et
                self.outputs["Q"] = True

        # Re-arm if running finished and IN dropped
        if not in_sig and self.outputs["ET"] >= pt:
            self.internal["running"] = False
            self.outputs["ET"] = 0.0

        self.internal["prev_in"] = in_sig

class CTU(IECFunctionBlock):
    """
    IEC 61131-3 CTU: Count-Up Counter.
    Inputs:
      CU: BOOL - Count Up trigger
      RESET: BOOL - Reset counter to 0
      PV: INT - Preset count value
    Outputs:
      Q: BOOL - Output (TRUE when CV >= PV)
      CV: INT - Current count value
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.inputs = {"CU": False, "RESET": False, "PV": 0}
        self.outputs = {"Q": False, "CV": 0}
        self.internal = {"prev_cu": False}

    def reset(self) -> None:
        self.inputs = {"CU": False, "RESET": False, "PV": 0}
        self.outputs = {"Q": False, "CV": 0}
        self.internal["prev_cu"] = False

    def execute(self, dt_ms: float = 0.0) -> None:
        cu = bool(self.inputs.get("CU", False))
        rst = bool(self.inputs.get("RESET", False))
        pv = int(self.inputs.get("PV", 0))
        prev_cu = self.internal["prev_cu"]

        if rst:
            self.outputs["CV"] = 0
            self.outputs["Q"] = False
        else:
            if cu and not prev_cu:  # Rising edge
                self.outputs["CV"] = int(self.outputs["CV"]) + 1
            self.outputs["Q"] = (self.outputs["CV"] >= pv)

        self.internal["prev_cu"] = cu

class CTD(IECFunctionBlock):
    """
    IEC 61131-3 CTD: Count-Down Counter.
    Inputs:
      CD: BOOL - Count Down trigger
      LOAD: BOOL - Load PV into CV
      PV: INT - Preset count value
    Outputs:
      Q: BOOL - Output (TRUE when CV <= 0)
      CV: INT - Current count value
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.inputs = {"CD": False, "LOAD": False, "PV": 0}
        self.outputs = {"Q": False, "CV": 0}
        self.internal = {"prev_cd": False}

    def reset(self) -> None:
        self.inputs = {"CD": False, "LOAD": False, "PV": 0}
        self.outputs = {"Q": False, "CV": 0}
        self.internal["prev_cd"] = False

    def execute(self, dt_ms: float = 0.0) -> None:
        cd = bool(self.inputs.get("CD", False))
        ld = bool(self.inputs.get("LOAD", False))
        pv = int(self.inputs.get("PV", 0))
        prev_cd = self.internal["prev_cd"]

        if ld:
            self.outputs["CV"] = pv
        else:
            if cd and not prev_cd:  # Rising edge
                self.outputs["CV"] = int(self.outputs["CV"]) - 1

        self.outputs["Q"] = (self.outputs["CV"] <= 0)
        self.internal["prev_cd"] = cd

class CTUD(IECFunctionBlock):
    """
    IEC 61131-3 CTUD: Count-Up / Count-Down Counter.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.inputs = {"CU": False, "CD": False, "RESET": False, "LOAD": False, "PV": 0}
        self.outputs = {"QU": False, "QD": False, "CV": 0}
        self.internal = {"prev_cu": False, "prev_cd": False}

    def reset(self) -> None:
        self.inputs = {"CU": False, "CD": False, "RESET": False, "LOAD": False, "PV": 0}
        self.outputs = {"QU": False, "QD": False, "CV": 0}
        self.internal["prev_cu"] = False
        self.internal["prev_cd"] = False

    def execute(self, dt_ms: float = 0.0) -> None:
        cu = bool(self.inputs.get("CU", False))
        cd = bool(self.inputs.get("CD", False))
        rst = bool(self.inputs.get("RESET", False))
        ld = bool(self.inputs.get("LOAD", False))
        pv = int(self.inputs.get("PV", 0))
        prev_cu = self.internal["prev_cu"]
        prev_cd = self.internal["prev_cd"]

        if rst:
            self.outputs["CV"] = 0
        elif ld:
            self.outputs["CV"] = pv
        else:
            cv = int(self.outputs["CV"])
            if cu and not prev_cu:
                cv += 1
            if cd and not prev_cd:
                cv -= 1
            self.outputs["CV"] = cv

        self.outputs["QU"] = (self.outputs["CV"] >= pv)
        self.outputs["QD"] = (self.outputs["CV"] <= 0)
        self.internal["prev_cu"] = cu
        self.internal["prev_cd"] = cd

STANDARD_FB_CLASSES = {
    "TON": TON,
    "TOF": TOF,
    "TP": TP,
    "CTU": CTU,
    "CTD": CTD,
    "CTUD": CTUD,
}

STANDARD_FUNCTIONS = {
    "ABS": lambda x: abs(x),
    "SQRT": lambda x: math.sqrt(x),
    "MIN": lambda a, b: min(a, b),
    "MAX": lambda a, b: max(a, b),
    "LIMIT": lambda mn, x, mx: max(mn, min(x, mx)),
    "MOD": lambda a, b: a % b,
    "SEL": lambda g, in0, in1: in1 if g else in0,
    "TRUNC": lambda x: math.trunc(x),
    "ROUND": lambda x: round(x),
    "INT_TO_REAL": lambda x: float(x),
    "REAL_TO_INT": lambda x: int(round(float(x))),
    "DINT_TO_REAL": lambda x: float(x),
    "REAL_TO_DINT": lambda x: int(round(float(x))),
    "INT_TO_DINT": lambda x: int(x),
    "DINT_TO_INT": lambda x: int(x),
    "BOOL_TO_INT": lambda x: 1 if x else 0,
    "INT_TO_BOOL": lambda x: bool(x),
    "REAL_TO_TIME": lambda x: float(x),
    "TIME_TO_REAL": lambda x: float(x),
}
