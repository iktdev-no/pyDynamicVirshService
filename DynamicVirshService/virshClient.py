from typing import Callable, List, Optional
import libvirt
from libvirt import virConnect, virDomain
import threading
import json
import logging


class VMStates:
    STATE_MAP = {
        libvirt.VIR_DOMAIN_NOSTATE: "no state",
        libvirt.VIR_DOMAIN_RUNNING: "running",
        libvirt.VIR_DOMAIN_BLOCKED: "blocked",
        libvirt.VIR_DOMAIN_PAUSED: "paused",
        libvirt.VIR_DOMAIN_SHUTDOWN: "shutdown",
        libvirt.VIR_DOMAIN_SHUTOFF: "shut off",
        libvirt.VIR_DOMAIN_CRASHED: "crashed",
        libvirt.VIR_DOMAIN_PMSUSPENDED: "suspended"
    }

    @staticmethod
    def get_state(state_code):
        return VMStates.STATE_MAP.get(state_code, "unknown")

class VirshVM:
    id: int | None
    name: str
    state: str
    
    def __init__(self, id: Optional[int], name: str, state: str):
        self.id = id
        self.name = name
        self.state = state

    def __repr__(self):
        return f"VirshVM(id={self.id}, name='{self.name}', state={self.state})"    
    

class VirshClient:
    client: virConnect | None = None
    qemu_address: str
    event_callback: None | Callable
    stopFlag = threading.Event()
    
    def __init__(self, qemu_address: str, event_callback=None) -> None:
        self.qemu_address = qemu_address
        self.event_callback = event_callback
        #self.client = libvirt.openReadOnly(None)
        # Registrer standard event loop før tilkobling
        libvirt.virEventRegisterDefaultImpl()
        self.client = libvirt.open(self.qemu_address)
        
        
    # Funksjon for å kjøre event_loop i egen tråd
    def start(self):
        self.stopFlag.clear()
        event_thread = threading.Thread(target=self.event_loop, daemon=True)
        event_thread.start()   
    
    def stop(self):
        self.stopFlag.set()     
        
    
    def get_vms(self) -> List[VirshVM]:
        vms: List[VirshVM] = []
        for vm in self.client.listAllDomains():
            id = None if vm.ID() == -1 else vm.ID()
            state, _ = vm.state()
            vms.append(VirshVM(
                id = id,
                name = vm.name(),
                state = VMStates.get_state(state)
            ))
        return vms
    
    # Funksjon for å håndtere VM-eventer
    def vm_event_handler(self, conn, dom: virDomain, event, detail, opaque):
        state, _ = dom.state()
        id = None if dom.ID() == -1 else dom.ID()
        vm = VirshVM(
            id = id,
            name = dom.name(),
            state = VMStates.get_state(state)
        )

        logging.info(f"VM with name: {vm.name} changed state to {vm.state}")                
        
        # Kall callback om den er definert
        if self.event_callback:
            self.event_callback(vm)
        
    # Lytte etter statusendringer i VM-er
    def event_loop(self):
        # Registrer callback for alle VM-er
        self.client.domainEventRegisterAny(None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, self.vm_event_handler, None)

        logging.info("Listening for VM events...")
        while not self.stopFlag.is_set():
            libvirt.virEventRunDefaultImpl()  # Kjør event-loop        