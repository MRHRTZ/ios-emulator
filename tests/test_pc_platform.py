import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import struct,unittest
from unittest.mock import patch
import mkadt,adt
from pc_session import PcSession,INPUT_MAGIC,INPUT_ADDRESS,map_pointer

class DeviceTreeTests(unittest.TestCase):
    def test_qemu_topology_roundtrip_and_rtc(self):
        with patch.object(mkadt,'d22ap_product',return_value=None):
            for count in (1,2,4):
                tree=adt.parse(adt.serialize(mkadt.build(qemu=True,cpu_count=count)))[0]
                cpus=next(n for n in tree.children if n.name=='cpus')
                regs=[struct.unpack('<I',dict((k,v) for k,f,v in n.props)['reg'])[0] for n in cpus.children]
                self.assertEqual(regs,list(range(count)))
                rtc=next(n for n in tree.children if n.name=='sweet-pc-rtc')
                self.assertEqual(struct.unpack('<QQ',dict((k,v) for k,f,v in rtc.props)['reg']),(0x09010000,0x1000))
    def test_phone_topology_and_peripherals_stay_separate(self):
        with patch.object(mkadt,'d22ap_product',return_value=None):
            tree=mkadt.build()
        self.assertNotIn('sweet-pc-rtc',[n.name for n in tree.children])
        cpus=next(n for n in tree.children if n.name=='cpus')
        self.assertEqual([struct.unpack('<I',dict((k,v) for k,f,v in n.props)['reg'])[0] for n in cpus.children],[i<<8 for i in range(8)])
        for count in (0,3,8):
            with self.assertRaises(ValueError):mkadt.build(qemu=True,cpu_count=count)

class MemoryChannel:
    def __init__(self,head=0,tail=0):
        self.header=[INPUT_MAGIC,1,head,tail,0,0,0,0];self.events=[]
    def read(self,address,size):return struct.pack('<8I',*self.header)
    def write(self,address,data):self.events.append((address,struct.unpack('<8I',data)))
    def write32(self,address,value):self.header[2]=value

class InputTests(unittest.TestCase):
    def session(self,head=0,tail=0):
        s=PcSession('.');s.input_ready=True;s.qtest=MemoryChannel(head,tail);return s
    def test_ring_full_rejects_release_without_forgetting_hold(self):
        s=self.session();self.assertTrue(s.input(1,0,True,540,2399))
        s.qtest.header[2]=65
        self.assertFalse(s.input(1,0,False,540,1200))
        self.assertIn((1,0),s.held_inputs)
        s.qtest.header[3]=65
        self.assertTrue(s.input(1,0,False,540,1200))
        self.assertFalse(s.held_inputs)
        self.assertEqual(s.qtest.events[-1][1][1:6],(1,0,0,540,1200))
    def test_ring_counter_wrap_keeps_sequence_and_slot_valid(self):
        s=self.session(0xffffffff,0xffffffff)
        self.assertTrue(s.input(2,0,True))
        self.assertEqual(s.qtest.events[0][0],INPUT_ADDRESS+64+63*32)
        self.assertEqual(s.qtest.events[0][1][0],0)
        self.assertEqual(s.qtest.header[2],0)
    def test_letterbox_and_rotated_edges(self):
        self.assertIsNone(map_pointer(0,0,20,30,108,240))
        self.assertEqual(map_pointer(128,270,20,30,108,240),(1079,2399))
        self.assertEqual(map_pointer(20,30,20,30,240,108,90),(0,2399))
        self.assertEqual(map_pointer(-100,999,20,30,240,108,90,True),(1079,2399))

class GuiTests(unittest.TestCase):
    def test_touch_area_has_no_tooltip_and_controls_have_names(self):
        from PySide6.QtWidgets import QApplication,QToolButton
        from PySide6.QtCore import QEvent
        from emulator_gui import Window
        app=QApplication.instance() or QApplication([])
        window=Window(auto_start=False)
        self.assertEqual(window.screen.toolTip(),'')
        self.assertTrue(window.screen.event(QEvent(QEvent.Type.ToolTip)))
        buttons=window.findChildren(QToolButton)
        names={b.accessibleName():b for b in buttons if b.accessibleName()}
        for name in ('Home','Apps','Power','Vol+','Vol-','Screenshot','Rotate','Fullscreen','Settings'):
            self.assertIn(name,names)
            self.assertEqual(names[name].text(),'')
            self.assertTrue(names[name].toolTip())
            self.assertFalse(names[name].icon().isNull())
        window.close()
