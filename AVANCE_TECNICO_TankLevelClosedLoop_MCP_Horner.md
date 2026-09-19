# Avance técnico — MCP Horner / Cscape TankLevelClosedLoop

**Fecha:** 2026-09-15 PT | **Entorno:** Windows 365 Cloud PC Armando Silva (2vCPU/8GB)  
**Repo:** `C:\HornerAI\horner-cscape-mcp\` | **Proyecto:** `TankLevelClosedLoop.csp`  
**PLC target:** XL4 Prime / HE-XPCE2 | CsCAN CAN1 IDs=1 | LAN1 ETN300 | IP `192.168.254.128/24`

## 1. Objetivo y estado
Objetivo: lazo cerrado de nivel vía MCP+Cscape, compile limpio, save/reopen, HMI+Trend offline, docs live  **sin** inventar `VERIFIED_LIVE`; download PLC solo por ingeniero.

**Estado 2026-09-15:** offline **CUMPLIDO**. Live/Force/SoftPLC bloqueados (`Local:Disconnected`). `VERIFIED_LIVE` **NO** reclamado.

## 2. Planes (no redefinir)
- Megaplan v1: G0?G5, H01–H13, fail-closed (`MEGAPLAN_TECNICO_MCP_HORNER_CSCAPE_v1.md`)
- Plan correctivo v2: C0C6 offline-first (`PLAN_CORRECTIVO_MCP_HORNER_CSCAPE_v2.md`)
- Orquestación: 1 PowerShell/agy; 1 GUI Cscape; ~15 agentes max; fail-closed si Cscape oculto; no pytest-as-gate.

## 3. Entregables
| Artefacto | Notas |
|-----------|-------|
| `TankLevelClosedLoop.csp` / `_HANDOFF.csp` | Vivo (lock si abierto) / Save As ~82KB |
| `horner-cscape-mcp_SOURCE.zip` | Fuente repo en Downloads (~48.5MB, CSP incluido) |
| `TankLevelClosedLoop_OFFLINE_HANDOFF_clean.zip` | ~39KB con CSP, sin scratch |
| `LEEME_HANDOFF.txt`, `DOWNLOAD_READY_NOTES.txt`, `OFFLINE_STATUS.md`, `LIVE_CONNECT_CHECKLIST.txt`, `LIVE_CONNECT_IO_MAP.txt`, `offline_package_ready.txt` | Handoff |

## 4. STBlock1 (lazo)
Tags: `Setpoint`,`TankLevelPV`,`Error`,`ControlOutput`,`Kp` (REAL); `TankLevelPV_I16`,`Setpoint_I16` (INT via ANY_TO_INT); `AlwaysOn:=TRUE`; `HI`/`LO`.
Trend rechazó REAL ? pens/bar usan I16. TankLogs: TankLevelPV (%R00006 histórico); UI Variables **no** muestra %R custom ? Force **por nombre**.
Force/SoftPLC offline: deshabilitados sin connect.

## 5. HMI
- Screen1: panel/gauge/bar/silueta
- Screen2 (~18 objs, reopen-ok): tanque, PV/SP, bar I16, HI/LO, ALARM, ControlOutput%, Error, Kp, Jump?3
- Screen3: pens PV_I16+SP_I16, trigger **AlwaysOn**, Jump?2, reopen-ok
- Error Check limpio + reopen proofs múltiples

## 6. Live prep (sin VERIFIED_LIVE)
IO map: XL4 HE-XPCE2, CsCAN, `192.168.254.128/24`, gw/dns 0.0.0.0, ~10 tags, sin %R en UI.
Gate: Connect PLC ? Force por tag ? evidencia GUI interactiva ? solo entonces VERIFIED_LIVE.

## 7. Cronología
- A (09-05?09): fail-closed / planes; cortar CONTINUE/pytest loops
- B (09-09?10): ST+HMI+Trend+docs producto
- C (09-10 noche): zip/SaveAs/IO map/clean zip
- D (09-11?15): watchdog 30min 8–22:30 PT; reconnect idle; esperar PLC

## 8. Matriz honesta
OK offline: ST, compile, reopen, Screen2/3, zip+CSP, docs/IO map.  
NO: SoftPLC/Force offline, Connect PLC, Download, VERIFIED_LIVE, gates G1–G5 formales.

## 9. Decisiones para otra IA
Offline-first; I16 bridge; AlwaysOn?HI; Save As vs CSP lock; Force by name; 1 PS; watchdog ligero.

## 10. Checklist evaluación
Abrir CSP ? STBlock1 tags ? Error Check 0 ? Screen2 binds ? Screen3 2 pens+AlwaysOn ? reopen ? leer IO map/checklist ? rechazar cualquier VERIFIED_LIVE sin PLC.

## 11. Deuda
CSP lock; zip Downloads lock; Cscape crash histórico; Cloud PC idle disconnect; falsos done agy; %R opacos.

## 12. Siguiente paso
Energizar XL4 ? Connect en Cscape ? Force/monitor tags ? evidencia live ? download solo por ingeniero.

## 13. Integridad
Informe **offline/DEV**. Claims live sin PLC = inválidos.
