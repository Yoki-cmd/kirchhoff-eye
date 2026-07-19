"""Internal models for deterministic electrical plausibility analysis."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


PinKey = Tuple[str, str]
PinRecord = Tuple[str, str, str]
NetEdge = Tuple[str, str]


@dataclass
class ElectricalGraph:
    document: dict
    component_pin_net: Dict[PinKey, str] = field(default_factory=dict)
    net_pins: Dict[str, List[PinRecord]] = field(default_factory=dict)
    component_nets: Dict[str, Dict[str, str]] = field(default_factory=dict)
    terminal_nets: Dict[int, Optional[str]] = field(default_factory=dict)
    ground_nets: Set[str] = field(default_factory=set)
    vcc_nets: Set[str] = field(default_factory=set)
    vee_nets: Set[str] = field(default_factory=set)
    dc_adjacency: Dict[str, Set[str]] = field(default_factory=dict)
    passive_adjacency: Dict[str, Set[str]] = field(default_factory=dict)
    device_edges: Dict[str, List[NetEdge]] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)
