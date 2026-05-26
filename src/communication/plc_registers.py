from src.utils.logger import logger
from src.exception.exception import ParameterError

logger = logger.bind(tag = "plc_registers")


# 夹爪寄存器地址
class GripperAddr:

    # 夹爪数量
    GRIPPER_COUNT = 6
    # 每个夹爪的寄存器数量
    REGISTERS_PER_GRIPPER = 3

    GRIPPER_1_POS = 0   # 夹爪1要夹取货物位置
    GRIPPER_1_COUNT = 1 # 对应库位货物数量
    GRIPPER_1_SIZE = 2  # 货物尺寸

    GRIPPER_2_POS = 3
    GRIPPER_2_COUNT = 4
    GRIPPER_2_SIZE = 5

    GRIPPER_3_POS = 6
    GRIPPER_3_COUNT = 7
    GRIPPER_3_SIZE = 8

    GRIPPER_4_POS = 9
    GRIPPER_4_COUNT = 10
    GRIPPER_4_SIZE = 11

    GRIPPER_5_POS = 12
    GRIPPER_5_COUNT = 13
    GRIPPER_5_SIZE = 14

    GRIPPER_6_POS = 15
    GRIPPER_6_COUNT = 16
    GRIPPER_6_SIZE = 17

    # 通过夹爪编号（1~6）获取该夹爪的抓取位置寄存器地址
    @classmethod
    def pos_addr(cls, gripper_id: int) -> int:
        cls._validate_gripper_id(gripper_id)
        return (gripper_id - 1) * cls.REGISTERS_PER_GRIPPER

    # 通过夹爪编号获取该夹爪的鞋盒数量寄存器地址
    @classmethod
    def count_addr(cls, gripper_id: int) -> int:
        cls._validate_gripper_id(gripper_id)
        return (gripper_id - 1) * cls.REGISTERS_PER_GRIPPER + 1

    # 通过夹爪编号获取该夹爪的鞋盒尺寸寄存器地址
    @classmethod
    def size_addr(cls, gripper_id: int) -> int:
        cls._validate_gripper_id(gripper_id)
        return (gripper_id - 1) * cls.REGISTERS_PER_GRIPPER + 2

    @classmethod
    def _validate_gripper_id(cls, gripper_id: int):
        if not 1 <= gripper_id <= cls.GRIPPER_COUNT:
            raise ParameterError(message=f"夹爪编号超出范围", expected_value=f"1~{cls.GRIPPER_COUNT}", actual_value=str(gripper_id))

    GRIPPER_1_PLACE_COUNT = 33 # 夹爪1放置鞋盒数量
    GRIPPER_2_PLACE_COUNT = 34 # 夹爪2放置鞋盒数量
    GRIPPER_3_PLACE_COUNT = 35 # 夹爪3放置鞋盒数量
    GRIPPER_4_PLACE_COUNT = 36 # 夹爪4放置鞋盒数量
    GRIPPER_5_PLACE_COUNT = 37 # 夹爪5放置鞋盒数量
    GRIPPER_6_PLACE_COUNT = 38 # 夹爪6放置鞋盒数量

    # 通过夹爪编号获取该夹爪的放货数量寄存器地址
    @classmethod
    def place_count_addr(cls, gripper_id: int) -> int:
        cls._validate_gripper_id(gripper_id)
        return 32 + gripper_id  # 即 (gripper_id - 1) + 33

    GRIPPER_1_NO_TASK = 66 # 夹爪1无任务寄存器，写1夹爪视为完成任务状态，不执行抓取任务
    GRIPPER_2_NO_TASK = 67
    GRIPPER_3_NO_TASK = 68
    GRIPPER_4_NO_TASK = 69
    GRIPPER_5_NO_TASK = 70
    GRIPPER_6_NO_TASK = 71

    @classmethod
    def no_task_addr(cls, gripper_id: int) -> int:
        cls._validate_gripper_id(gripper_id)
        return 65 + gripper_id

# 库位移动
class LocationMoveAddr:
    MOVE_PICK_START = 73   # 夹爪1移动抓取位置
    MOVE_PLACE_START = 79  # 夹爪1移动放置位置


    @classmethod
    def move_pick_addr(cls, gripper_id: int) -> int:
        # gripper_id 1~6 -> D73~D78
        GripperAddr._validate_gripper_id(gripper_id)
        return 72 + gripper_id  # 即 (gripper_id - 1) + 73

    @classmethod
    def move_place_addr(cls, gripper_id: int) -> int:
        # gripper_id 1~6 -> D79~D84
        GripperAddr._validate_gripper_id(gripper_id)
        return 78 + gripper_id  # 即 (gripper_id - 1) + 79



# 库位传送带寄存器
class CabinetCtrlAddr:

    # 工作站数量
    STATION_COUNT = 3
    # 工作站寄存器数量
    REGISTERS_PER_STATION = 5

    WSA_PLACE = 18          # 工作站A库位传送带集体转动
    WSA_L1_FWD = 19         # 1层传送带转动
    WSA_L2_FWD = 20         # 2层传送带转动
    WSA_L3_FWD = 21         # 3层传送带转动
    WSA_L4_FWD = 22         # 4层传送带转动

    WSB_PLACE = 23          # 工作站B库位传送带集体转动
    WSB_L1_FWD = 24         # 1层传送带转动
    WSB_L2_FWD = 25         # 2层传送带转动
    WSB_L3_FWD = 26         # 3层传送带转动
    WSB_L4_FWD = 27         # 4层传送带转动

    WSC_PLACE = 28         # 工作站C库位传送带集体转动
    WSC_L1_FWD = 29         # 1层传送带转动
    WSC_L2_FWD = 30         # 2层传送带转动
    WSC_L3_FWD = 31         # 3层传送带转动
    WSC_L4_FWD = 32         # 4层传送带转动


    WSA_L1_NO_BOX = 39  # 工作站1 一层收纳柜放货时无鞋盒
    WSA_L2_NO_BOX = 40
    WSA_L3_NO_BOX = 41
    WSA_L4_NO_BOX = 42
    WSB_L1_NO_BOX = 43
    WSB_L2_NO_BOX = 44
    WSB_L3_NO_BOX = 45
    WSB_L4_NO_BOX = 46
    WSC_L1_NO_BOX = 47
    WSC_L2_NO_BOX = 48
    WSC_L3_NO_BOX = 49
    WSC_L4_NO_BOX = 50

    WSA_L1_BACK = 51   # 工作站A1层库位传送带后退
    WSA_L2_BACK = 52   # 工作站A2层库位传送带后退
    WSA_L3_BACK = 53   # 工作站A3层库位传送带后退
    WSA_L4_BACK = 54   # 工作站A4层库位传送带后退
    WSB_L1_BACK = 55   # 工作站B1层库位传送带后退
    WSB_L2_BACK = 56   # 工作站B2层库位传送带后退
    WSB_L3_BACK = 57   # 工作站B3层库位传送带后退
    WSB_L4_BACK = 58   # 工作站B4层库位传送带后退
    WSC_L1_BACK = 59   # 工作站C1层库位传送带后退
    WSC_L2_BACK = 60   # 工作站C2层库位传送带后退
    WSC_L3_BACK = 61   # 工作站C3层库位传送带后退
    WSC_L4_BACK = 62   # 工作站C4层库位传送带后退



    # 通过工作站编号获取库位集体转动地址
    @classmethod
    def place_addr(cls, station_id: int) -> int:
        cls._validate_station_id(station_id)
        return 18 + (station_id - 1) * cls.REGISTERS_PER_STATION

    # 通过工作站编号和层号获取库位传送带前进地址
    @classmethod
    def forward_addr(cls, station_id: int, layer: int) -> int:
        cls._validate_station_id(station_id)
        if not 1 <= layer <= 4:
            raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(layer))
        return 18 + (station_id - 1) * cls.REGISTERS_PER_STATION + layer

    # 通过工作站编号和层号获取放货时无鞋盒需要跳过的传送带地址
    @classmethod
    def no_box_addr(cls, station_id: int, layer: int) -> int:
        cls._validate_station_id(station_id)
        if not 1 <= layer <= 4:
            raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(layer))
        return 38 + (station_id - 1) * 4 + layer

    @classmethod
    def backward_addr(cls, station_id: int, layer: int) -> int:
        cls._validate_station_id(station_id)
        if not 1 <= layer <= 4:
            raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(layer))
        return 50 + (station_id - 1) * 4 + layer

    @classmethod
    def _validate_station_id(cls, station_id: int):
        if not 1 <= station_id <= cls.STATION_COUNT:
            raise ParameterError(message=f"工作站编号超出范围", expected_value=f"1~{cls.STATION_COUNT}", actual_value=str(station_id))


# 状态寄存器
class StatusAddr:

    GRIPPER_1_STATUS = 100   # 夹爪1当前状态 1=运行中, 0=空闲
    GRIPPER_2_STATUS = 101
    GRIPPER_3_STATUS = 102
    GRIPPER_4_STATUS = 103
    GRIPPER_5_STATUS = 104
    GRIPPER_6_STATUS = 105

    GRIPPER_STATUS_START = 100 # 夹爪状态寄存器起始地址
    GRIPPER_STATUS_COUNT = 6   # 夹爪状态寄存器数量

    # 获得夹爪状态寄存器地址
    @classmethod
    def gripper_status_addr(cls, gripper_id: int) -> int:
        if not 1 <= gripper_id <= 6:
            raise ParameterError(message="夹爪编号超出范围", expected_value="1~6", actual_value=str(gripper_id))
        return 99 + gripper_id

    WSA_CB1_S = 106 # 工作站A库位传送带状态， 1传送带运行中，0传送带停止
    WSA_CB2_S = 107
    WSA_CB3_S = 108
    WSA_CB4_S = 109
    WSB_CB1_S = 110
    WSB_CB2_S = 111
    WSB_CB3_S = 112
    WSB_CB4_S = 113
    WSC_CB1_S = 114
    WSC_CB2_S = 115
    WSC_CB3_S = 116
    WSC_CB4_S = 117

    CONVEYOR_STATUS_START = 106 # 传送带状态寄存器起始地址
    CONVEYOR_STATUS_COUNT = 12 # 传送带寄存器数量

    # 获取工作站传送带状态寄存器地址
    @classmethod
    def conveyor_status_addr(cls, station_id: int, layer: int) -> int:
        if not 1 <= station_id <= 3:
            raise ParameterError(message="工作站编号超出范围", expected_value="1~3", actual_value=str(station_id))
        if not 1 <= layer <= 4:
            raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(layer))
        return 105 + (station_id - 1) * 4 + layer

    WSA_1F_PS_S = 118 # 工作站A1层前光电传感器状态，1光电触发，0未触发
    WSA_1B_PS_S = 119 # 工作站A1层后光电传感器状态，1光电触发，0未触发
    WSA_2F_PS_S = 120 # 工作站A2层前光电传感器状态，1光电触发，0未触发
    WSA_2B_PS_S = 121 # 工作站A2层后光电传感器状态，1光电触发，0未触发
    WSA_3F_PS_S = 122 # 工作站A3层前光电传感器状态，1光电触发，0未触发
    WSA_3B_PS_S = 123 # 工作站A3层后光电传感器状态，1光电触发，0未触发
    WSA_4F_PS_S = 124 # 工作站A4层前光电传感器状态，1光电触发，0未触发
    WSA_4B_PS_S = 125 # 工作站A4层后光电传感器状态，1光电触发，0未触发
    WSB_1F_PS_S = 126 # 工作站B1层前光电传感器状态，1光电触发，0未触发
    WSB_1B_PS_S = 127 # 工作站B1层后光电传感器状态，1光电触发，0未触发
    WSB_2F_PS_S = 128 # 工作站B2层前光电传感器状态，1光电触发，0未触发
    WSB_2B_PS_S = 129 # 工作站B2层后光电传感器状态，1光电触发，0未触发
    WSB_3F_PS_S = 130 # 工作站B3层前光电传感器状态，1光电触发，0未触发
    WSB_3B_PS_S = 131 # 工作站B3层后光电传感器状态，1光电触发，0未触发
    WSB_4F_PS_S = 132 # 工作站B4层前光电传感器状态，1光电触发，0未触发
    WSB_4B_PS_S = 133 # 工作站B4层后光电传感器状态，1光电触发，0未触发
    WSC_1F_PS_S = 134 # 工作站C1层前光电传感器状态，1光电触发，0未触发
    WSC_1B_PS_S = 135 # 工作站C1层后光电传感器状态，1光电触发，0未触发
    WSC_2F_PS_S = 136 # 工作站C2层前光电传感器状态，1光电触发，0未触发
    WSC_2B_PS_S = 137 # 工作站C2层后光电传感器状态，1光电触发，0未触发
    WSC_3F_PS_S = 138 # 工作站C3层前光电传感器状态，1光电触发，0未触发
    WSC_3B_PS_S = 139 # 工作站C3层后光电传感器状态，1光电触发，0未触发
    WSC_4F_PS_S = 140 # 工作站C4层前光电传感器状态，1光电触发，0未触发
    WSC_4B_PS_S = 141 # 工作站C4层后光电传感器状态，1光电触发，0未触发

    PHOTO_START = 118 # 光电传感器起始地址
    PHOTO_COUNT = 24  # 光电传感器数量

    #获取光电传感器地址。
    @classmethod
    def photo_addr(cls, station_id: int, layer: int, position: str) -> int:

        if not 1 <= station_id <= 3:
            raise ParameterError(message="工作站编号超出范围", expected_value="1~3", actual_value=str(station_id))
        if not 1 <= layer <= 4:
            raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(layer))
        if position not in ("front", "back"):
            raise ParameterError(message="光电位置参数错误", expected_value="front 或 back", actual_value=str(position))

        index = (station_id - 1) * 8 + (layer - 1) * 2
        if position == "back":
            index += 1
        return 118 + index

    WSA_LSF_E = 142 # 工作站A左夹爪伸缩故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSA_LLF_E = 143 # 工作站A左夹爪升降故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSA_RSF_E = 144 # 工作站A右夹爪伸缩故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSA_RLF_E = 145 # 工作站A右夹爪升降故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSB_LSF_E = 146 # 工作站B左夹爪伸缩故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSB_LLF_E = 147 # 工作站B左夹爪升降故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSB_RSF_E = 148 # 工作站B右夹爪伸缩故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSB_RLF_E = 149 # 工作站B右夹爪升降故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSC_LSF_E = 150 # 工作站C左夹爪伸缩故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSC_LLF_E = 151 # 工作站C左夹爪升降故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSC_RSF_E = 152 # 工作站C右夹爪伸缩故障，0为无故障，大于0则轴故障，读取到的数值为故障码
    WSC_RLF_E = 153 # 工作站C右夹爪升降故障，0为无故障，大于0则轴故障，读取到的数值为故障码

    FAULT_START = 142 # 夹爪轴故障寄存器起始地址
    FAULT_COUNT = 12  # 夹爪轴故障寄存器数量

    AXLE_NAMES = ("left_stretch", "left_lift", "right_stretch", "right_lift")

    # 获取夹爪轴故障寄存器起始地址
    @classmethod
    def fault_addr(cls, station_id: int, axle: str) -> int:
        if not 1 <= station_id <= 3:
            raise ParameterError(message="工作站编号超出范围", expected_value="1~3", actual_value=str(station_id))
        if axle not in cls.AXLE_NAMES:
            raise ParameterError(message="轴名称参数错误", expected_value=str(cls.AXLE_NAMES), actual_value=str(axle))
        axle_index = cls.AXLE_NAMES.index(axle)
        return 142 + (station_id - 1) * 4 + axle_index

    EMERGENCY_STOP = 154 # 急停报警

    WSA_1TO_E = 155 # 工作站A1层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSA_2TO_E = 156 # 工作站A2层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSA_3TO_E = 157 # 工作站A3层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSA_4TO_E = 158 # 工作站A4层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSB_1TO_E = 159 # 工作站B1层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSB_2TO_E = 160 # 工作站B2层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSB_3TO_E = 161 # 工作站B3层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSB_4TO_E = 162 # 工作站B4层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSC_1TO_E = 163 # 工作站C1层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSC_2TO_E = 164 # 工作站C2层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSC_3TO_E = 165 # 工作站C3层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0
    WSC_4TO_E = 166 # 工作站C4层库位传送带运行时间过久光电未检测到鞋盒，故障恢复后需上位机清0

    TIMEOUT_START = 155 # 工作站库位传送带运行状态超时报警寄存器起始地址
    TIMEOUT_COUNT = 12  # 工作站库位传送带运行状态超时报警寄存器数量

    # 获得工作站库位传送带运行超时报警寄存器地址
    @classmethod
    def timeout_addr(cls, station_id: int, layer: int) -> int:
        if not 1 <= station_id <= 3:
            raise ParameterError(message="工作站编号超出范围", expected_value="1~3", actual_value=str(station_id))
        if not 1 <= layer <= 4:
            raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(layer))
        return 154 + (station_id - 1) * 4 + layer

class OutboundAddr:
    BATCH_COUNT = 63
    COMPLETE_FLAG = 64
    PHOTO_COUNT = 65

# 全局地址区间
class RegisterRange:

    CTRL_START = 0           # 控制区起始地址
    CTRL_END = 84            # 控制区结束地址
    CTRL_COUNT = 85          # 控制区寄存器总数

    STATUS_START = 100       # 状态区起始地址
    STATUS_END = 166         # 状态区结束地址
    STATUS_COUNT = 67        # 状态区寄存器总数
