# coding:utf-8
import sys
import os
import re
import csv
import json
import subprocess
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon, QColor, QFont, QTextCursor
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPlainTextEdit, QLabel, QFrame)

# qfluentwidgets 在导入时会创建 QWidget，必须先创建 QApplication
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
app = QApplication(sys.argv)

from qfluentwidgets import (MSFluentWindow, FluentIcon as FIF, setTheme, Theme,
                            ScrollArea, ExpandLayout, SettingCardGroup, SettingCard,
                            LineEdit, ComboBox, SpinBox, DoubleSpinBox,
                            PrimaryPushButton, PushButton,
                            InfoBar, InfoBarPosition)
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu


class FixedComboBox(ComboBox):
    """修复弹出菜单外层边框的 ComboBox"""

    def _createComboMenu(self):
        menu = ComboBoxMenu(self)
        menu.setShadowEffect(blurRadius=0, offset=(0, 0), color=QColor(0, 0, 0, 0))
        menu.layout().setContentsMargins(0, 0, 0, 0)
        return menu


CTRL_WIDTH = 200

# PyInstaller 打包后 __file__ 指向临时目录，需要用 sys.executable 定位 exe 所在目录
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def loadModels():
    """从 models.csv 加载模型映射表，返回 (llm_dict, mm_dict)，均为 {显示名: 路径}"""
    csv_path = os.path.join(BASE_DIR, 'models.csv')
    llm_models = {}
    mm_models = {}
    if os.path.exists(csv_path):
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.reader(f):
                if len(row) < 3:
                    continue
                mtype, name, path = row[0].strip(), row[1].strip(), row[2].strip()
                if mtype == 'm':
                    llm_models[name] = path
                elif mtype == 'mm':
                    mm_models[name] = path
    return llm_models, mm_models


class BaseSettingInterface(ScrollArea):
    """设置页面基类，统一处理滚动区域 + 标题 + ExpandLayout"""

    def __init__(self, title: str, object_name: str, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)

        self.titleLabel = QLabel(title, self)
        self.titleLabel.setObjectName('settingLabel')

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 80, 0, 0)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName(object_name)
        self.setStyleSheet('background: transparent; border: none;')
        self.viewport().setStyleSheet('background: transparent;')

        self.scrollWidget.setObjectName('scrollWidget')
        self.scrollWidget.setStyleSheet('background: transparent;')
        self.titleLabel.move(36, 30)
        self.titleLabel.setStyleSheet('font: 33px "Segoe UI", "Microsoft YaHei"; background: transparent;')

        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)


class BasicInterface(QFrame):
    """基础设置：程序路径 + 命令预览（自适应高度）"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('basic-interface')
        self.setStyleSheet('background: transparent; border: none;')

        mainLayout = QVBoxLayout(self)
        mainLayout.setContentsMargins(36, 30, 36, 20)
        mainLayout.setSpacing(0)

        self.titleLabel = QLabel('基础设置', self)
        self.titleLabel.setStyleSheet('font: 33px "Segoe UI", "Microsoft YaHei"; background: transparent;')
        mainLayout.addWidget(self.titleLabel)
        mainLayout.addSpacing(30)

        # ─────────── 路径配置 ───────────
        self.pathGroup = SettingCardGroup('路径配置', self)
        self.execPathCard = SettingCard(FIF.COMMAND_PROMPT, '程序路径', '设置 llama-server 在 WSL 中的可执行文件路径', self.pathGroup)
        self.execPathEdit = LineEdit(self.execPathCard)
        self.execPathEdit.setPlaceholderText('~/llama.cpp/build/bin/llama-server')
        self.execPathEdit.setText('~/llama.cpp/build/bin/llama-server')
        self.execPathEdit.setFixedWidth(300)
        self.execPathCard.hBoxLayout.addWidget(self.execPathEdit, 0, Qt.AlignRight)
        self.execPathCard.hBoxLayout.addSpacing(16)
        self.pathGroup.addSettingCard(self.execPathCard)
        mainLayout.addWidget(self.pathGroup)
        mainLayout.addSpacing(28)

        # ─────────── 命令预览 ───────────
        previewLabel = QLabel('命令预览', self)
        previewLabel.setStyleSheet('font: 20px "Segoe UI", "Microsoft YaHei"; color: white; background: transparent;')
        mainLayout.addWidget(previewLabel)
        mainLayout.addSpacing(12)

        self.cmdPreview = QTextEdit(self)
        self.cmdPreview.setReadOnly(True)
        self.cmdPreview.setStyleSheet('background: rgba(255,255,255,0.04); border: none; border-radius: 8px; color: rgba(255,255,255,0.8); font: 13px "Consolas", "Microsoft YaHei"; padding: 12px 16px;')
        mainLayout.addWidget(self.cmdPreview, 1)
        mainLayout.addSpacing(12)

        # ─────────── 底部运行按钮 ───────────
        self.runBtn = PrimaryPushButton(FIF.PLAY, '运行', self)
        self.runBtn.setFixedHeight(40)
        mainLayout.addWidget(self.runBtn)


class ModelInterface(BaseSettingInterface):
    """模型设置"""

    def __init__(self, llm_models=None, mm_models=None, parent=None):
        super().__init__('模型设置', 'model-interface', parent)
        self.llmPaths = llm_models or {}
        self.mmPaths = mm_models or {}

        self.modelGroup = SettingCardGroup('模型选择', self.scrollWidget)

        # 大模型选择
        self.llmCard = SettingCard(FIF.IOT, '大语言模型', '选择要加载的 GGUF 模型文件', self.modelGroup)
        self.llmCombo = FixedComboBox(self.llmCard)
        self.llmCombo.addItems(list(self.llmPaths.keys()))
        self.llmCombo.setFixedWidth(CTRL_WIDTH)
        self.llmCard.hBoxLayout.addWidget(self.llmCombo, 0, Qt.AlignRight)
        self.llmCard.hBoxLayout.addSpacing(16)

        # 多模态模型选择
        self.mmCard = SettingCard(FIF.PHOTO, '多模态模型', '选择多模态投影器文件（可选）', self.modelGroup)
        self.mmCombo = FixedComboBox(self.mmCard)
        self.mmCombo.addItems(['无'] + list(self.mmPaths.keys()))
        self.mmCombo.setFixedWidth(CTRL_WIDTH)
        self.mmCard.hBoxLayout.addWidget(self.mmCombo, 0, Qt.AlignRight)
        self.mmCard.hBoxLayout.addSpacing(16)

        self.modelGroup.addSettingCard(self.llmCard)
        self.modelGroup.addSettingCard(self.mmCard)
        self.expandLayout.addWidget(self.modelGroup)

        # ─────────── 模型参数 ───────────
        self.paramGroup = SettingCardGroup('模型参数', self.scrollWidget)

        # 上下文长度 (-c)
        self.ctxCard = SettingCard(FIF.SCROLL, '上下文长度', '提示词上下文窗口大小，值越大能处理越长的对话（默认 2048）', self.paramGroup)
        self.ctxEdit = LineEdit(self.ctxCard)
        self.ctxEdit.setText('128')
        self.ctxEdit.setFixedWidth(100)
        from PySide6.QtGui import QIntValidator
        self.ctxEdit.setValidator(QIntValidator(1, 9999, self.ctxEdit))
        self.ctxSuffix = QLabel('K', self.ctxCard)
        self.ctxSuffix.setStyleSheet('font: 14px; background: transparent;')
        self.ctxCard.hBoxLayout.addWidget(self.ctxEdit, 0, Qt.AlignRight)
        self.ctxCard.hBoxLayout.addSpacing(8)
        self.ctxCard.hBoxLayout.addWidget(self.ctxSuffix)
        self.ctxCard.hBoxLayout.addSpacing(16)

        # 最大生成长度 (-n)
        self.predictCard = SettingCard(FIF.EDIT, '最大生成长度', '单次最多生成的 token 数，-1 为无限制（默认 -1）', self.paramGroup)
        self.predictEdit = LineEdit(self.predictCard)
        self.predictEdit.setText('-1')
        self.predictEdit.setFixedWidth(CTRL_WIDTH)
        from PySide6.QtGui import QIntValidator
        self.predictEdit.setValidator(QIntValidator(-1, 999999, self.predictEdit))
        self.predictCard.hBoxLayout.addWidget(self.predictEdit, 0, Qt.AlignRight)
        self.predictCard.hBoxLayout.addSpacing(16)

        # 温度 (--temp)
        self.tempCard = SettingCard(FIF.CALORIES, '温度', '控制输出随机性，越高越随机/有创意，越低越确定/保守（默认 0.7）', self.paramGroup)
        self.tempSpin = DoubleSpinBox(self.tempCard)
        self.tempSpin.setRange(0.0, 2.0)
        self.tempSpin.setValue(0.7)
        self.tempSpin.setSingleStep(0.1)
        self.tempSpin.setDecimals(2)
        self.tempSpin.setFixedWidth(CTRL_WIDTH)
        self.tempCard.hBoxLayout.addWidget(self.tempSpin, 0, Qt.AlignRight)
        self.tempCard.hBoxLayout.addSpacing(16)

        # Top-P (--top-p)
        self.topPCard = SettingCard(FIF.MARKET, 'Top-P', '核采样，只从累计概率达到 P 的最小 token 集合中采样（默认 0.9）', self.paramGroup)
        self.topPSpin = DoubleSpinBox(self.topPCard)
        self.topPSpin.setRange(0.0, 1.0)
        self.topPSpin.setValue(0.9)
        self.topPSpin.setSingleStep(0.05)
        self.topPSpin.setDecimals(2)
        self.topPSpin.setFixedWidth(CTRL_WIDTH)
        self.topPCard.hBoxLayout.addWidget(self.topPSpin, 0, Qt.AlignRight)
        self.topPCard.hBoxLayout.addSpacing(16)

        # Top-K (--top-k)
        self.topKCard = SettingCard(FIF.FILTER, 'Top-K', '只从概率最高的 K 个 token 中采样（默认 40）', self.paramGroup)
        self.topKSpin = SpinBox(self.topKCard)
        self.topKSpin.setRange(0, 200)
        self.topKSpin.setValue(40)
        self.topKSpin.setFixedWidth(CTRL_WIDTH)
        self.topKCard.hBoxLayout.addWidget(self.topKSpin, 0, Qt.AlignRight)
        self.topKCard.hBoxLayout.addSpacing(16)

        # 重复惩罚 (--repeat-penalty)
        self.repeatPenaltyCard = SettingCard(FIF.REMOVE, '重复惩罚', '对已出现的 token 施加惩罚以减少重复，1.0 为不惩罚（默认 1.1）', self.paramGroup)
        self.repeatPenaltySpin = DoubleSpinBox(self.repeatPenaltyCard)
        self.repeatPenaltySpin.setRange(0.0, 2.0)
        self.repeatPenaltySpin.setValue(1.1)
        self.repeatPenaltySpin.setSingleStep(0.1)
        self.repeatPenaltySpin.setDecimals(2)
        self.repeatPenaltySpin.setFixedWidth(CTRL_WIDTH)
        self.repeatPenaltyCard.hBoxLayout.addWidget(self.repeatPenaltySpin, 0, Qt.AlignRight)
        self.repeatPenaltyCard.hBoxLayout.addSpacing(16)

        # 惩罚回溯窗口 (--repeat-last-n)
        self.repeatLastNCard = SettingCard(FIF.HISTORY, '惩罚回溯窗口', '重复惩罚回溯的 token 数量（默认 64）', self.paramGroup)
        self.repeatLastNSpin = SpinBox(self.repeatLastNCard)
        self.repeatLastNSpin.setRange(0, 4096)
        self.repeatLastNSpin.setValue(64)
        self.repeatLastNSpin.setFixedWidth(CTRL_WIDTH)
        self.repeatLastNCard.hBoxLayout.addWidget(self.repeatLastNSpin, 0, Qt.AlignRight)
        self.repeatLastNCard.hBoxLayout.addSpacing(16)

        self.paramGroup.addSettingCard(self.ctxCard)
        self.paramGroup.addSettingCard(self.predictCard)
        self.paramGroup.addSettingCard(self.tempCard)
        self.paramGroup.addSettingCard(self.topPCard)
        self.paramGroup.addSettingCard(self.topKCard)
        self.paramGroup.addSettingCard(self.repeatPenaltyCard)
        self.paramGroup.addSettingCard(self.repeatLastNCard)
        self.expandLayout.addWidget(self.paramGroup)

        # ─────────── KV 缓存 ───────────
        self.kvGroup = SettingCardGroup('KV 缓存', self.scrollWidget)

        # K 缓存精度 (--cache-type-k)
        self.cacheKCard = SettingCard(FIF.SPEED_OFF, 'K 缓存精度', '低精度省显存但可能影响质量（默认 f16）', self.kvGroup)
        self.cacheKCombo = FixedComboBox(self.cacheKCard)
        self.cacheKCombo.addItems(['f32', 'f16', 'bf16', 'q8_0', 'q4_0', 'q4_1', 'iq4_nl', 'q5_0', 'q5_1', 'turbo2', 'turbo3', 'turbo4'])
        self.cacheKCombo.setCurrentText('f16')
        self.cacheKCombo.setFixedWidth(CTRL_WIDTH)
        self.cacheKCard.hBoxLayout.addWidget(self.cacheKCombo, 0, Qt.AlignRight)
        self.cacheKCard.hBoxLayout.addSpacing(16)

        # V 缓存精度 (--cache-type-v)
        self.cacheVCard = SettingCard(FIF.SPEED_HIGH, 'V 缓存精度', '低精度省显存但可能影响质量（默认 f16）', self.kvGroup)
        self.cacheVCombo = FixedComboBox(self.cacheVCard)
        self.cacheVCombo.addItems(['f32', 'f16', 'bf16', 'q8_0', 'q4_0', 'q4_1', 'iq4_nl', 'q5_0', 'q5_1', 'turbo2', 'turbo3', 'turbo4'])
        self.cacheVCombo.setCurrentText('f16')
        self.cacheVCombo.setFixedWidth(CTRL_WIDTH)
        self.cacheVCard.hBoxLayout.addWidget(self.cacheVCombo, 0, Qt.AlignRight)
        self.cacheVCard.hBoxLayout.addSpacing(16)

        # KV 缓存大小 (--cache-ram)
        self.cacheRamCard = SettingCard(FIF.SAVE, 'KV 缓存大小', 'KV 缓存的内存上限，留空为自动（单位 MB）', self.kvGroup)
        self.cacheRamEdit = LineEdit(self.cacheRamCard)
        self.cacheRamEdit.setPlaceholderText('auto')
        self.cacheRamEdit.setFixedWidth(100)
        self.cacheRamSuffix = QLabel('MB', self.cacheRamCard)
        self.cacheRamSuffix.setStyleSheet('font: 14px; background: transparent;')
        self.cacheRamCard.hBoxLayout.addWidget(self.cacheRamEdit, 0, Qt.AlignRight)
        self.cacheRamCard.hBoxLayout.addSpacing(8)
        self.cacheRamCard.hBoxLayout.addWidget(self.cacheRamSuffix)
        self.cacheRamCard.hBoxLayout.addSpacing(16)

        # Flash Attention (--flash-attn)
        self.faCard = SettingCard(FIF.SPEED_MEDIUM, 'Flash Attention', '加速推理并降低显存占用（默认 auto）', self.kvGroup)
        self.faCombo = FixedComboBox(self.faCard)
        self.faCombo.addItems(['auto', 'on', 'off'])
        self.faCombo.setCurrentText('auto')
        self.faCombo.setFixedWidth(CTRL_WIDTH)
        self.faCard.hBoxLayout.addWidget(self.faCombo, 0, Qt.AlignRight)
        self.faCard.hBoxLayout.addSpacing(16)

        self.kvGroup.addSettingCard(self.cacheKCard)
        self.kvGroup.addSettingCard(self.cacheVCard)
        self.kvGroup.addSettingCard(self.cacheRamCard)
        self.kvGroup.addSettingCard(self.faCard)
        self.expandLayout.addWidget(self.kvGroup)

        # ─────────── 多模态参数 ───────────
        self.mmParamGroup = SettingCardGroup('多模态参数', self.scrollWidget)

        # 图像最大 Token 数 (--image-max-tokens)
        self.imgMaxCard = SettingCard(FIF.PHOTO, '图像最大 Token 数', '动态分辨率模型中每张图像的最大 Token 数（留空读取模型默认值）', self.mmParamGroup)
        self.imgMaxEdit = LineEdit(self.imgMaxCard)
        self.imgMaxEdit.setPlaceholderText('模型默认')
        self.imgMaxEdit.setFixedWidth(CTRL_WIDTH)
        self.imgMaxCard.hBoxLayout.addWidget(self.imgMaxEdit, 0, Qt.AlignRight)
        self.imgMaxCard.hBoxLayout.addSpacing(16)

        # 图像最小 Token 数 (--image-min-tokens)
        self.imgMinCard = SettingCard(FIF.PHOTO, '图像最小 Token 数', '动态分辨率模型中每张图像的最小 Token 数（留空读取模型默认值）', self.mmParamGroup)
        self.imgMinEdit = LineEdit(self.imgMinCard)
        self.imgMinEdit.setPlaceholderText('模型默认')
        self.imgMinEdit.setFixedWidth(CTRL_WIDTH)
        self.imgMinCard.hBoxLayout.addWidget(self.imgMinEdit, 0, Qt.AlignRight)
        self.imgMinCard.hBoxLayout.addSpacing(16)

        self.mmParamGroup.addSettingCard(self.imgMaxCard)
        self.mmParamGroup.addSettingCard(self.imgMinCard)
        self.expandLayout.addWidget(self.mmParamGroup)

        # ─────────── GPU 加速 ───────────
        self.gpuGroup = SettingCardGroup('GPU 加速', self.scrollWidget)

        # GPU 层数 (-ngl)
        self.nglCard = SettingCard(FIF.SPEED_HIGH, 'GPU 层数', '将模型的前 N 层卸载到 GPU，设为 999 可将整个模型放入 GPU（默认 999）', self.gpuGroup)
        self.nglSpin = SpinBox(self.nglCard)
        self.nglSpin.setRange(0, 999)
        self.nglSpin.setValue(999)
        self.nglSpin.setFixedWidth(CTRL_WIDTH)
        self.nglCard.hBoxLayout.addWidget(self.nglSpin, 0, Qt.AlignRight)
        self.nglCard.hBoxLayout.addSpacing(16)

        # 主 GPU (-mg)
        self.mainGpuCard = SettingCard(FIF.DEVELOPER_TOOLS, '主 GPU', '多 GPU 时指定主 GPU 的设备 ID（默认 0）', self.gpuGroup)
        self.mainGpuSpin = SpinBox(self.mainGpuCard)
        self.mainGpuSpin.setRange(0, 15)
        self.mainGpuSpin.setValue(0)
        self.mainGpuSpin.setFixedWidth(CTRL_WIDTH)
        self.mainGpuCard.hBoxLayout.addWidget(self.mainGpuSpin, 0, Qt.AlignRight)
        self.mainGpuCard.hBoxLayout.addSpacing(16)

        # 张量分割比例 (-ts)
        self.tsSplitCard = SettingCard(FIF.SYNC, '张量分割比例', '多 GPU 时各 GPU 负载比例，如 3,7 表示 30%/70%（留空为均分）', self.gpuGroup)
        self.tsSplitEdit = LineEdit(self.tsSplitCard)
        self.tsSplitEdit.setPlaceholderText('均分')
        self.tsSplitEdit.setFixedWidth(CTRL_WIDTH)
        self.tsSplitCard.hBoxLayout.addWidget(self.tsSplitEdit, 0, Qt.AlignRight)
        self.tsSplitCard.hBoxLayout.addSpacing(16)

        # 禁用内存映射 (--no-mmap)
        self.nommapCard = SettingCard(FIF.REMOVE, '禁用内存映射', '不使用 mmap 加载模型，改为直接读入内存（默认启用 mmap）', self.gpuGroup)
        self.nommapCombo = FixedComboBox(self.nommapCard)
        self.nommapCombo.addItems(['关闭', '启用'])
        self.nommapCombo.setFixedWidth(CTRL_WIDTH)
        self.nommapCard.hBoxLayout.addWidget(self.nommapCombo, 0, Qt.AlignRight)
        self.nommapCard.hBoxLayout.addSpacing(16)

        # NUMA 优化 (--numa)
        self.numaCard = SettingCard(FIF.CONNECT, 'NUMA 优化', '多路 CPU 服务器性能优化策略（默认关闭）', self.gpuGroup)
        self.numaCombo = FixedComboBox(self.numaCard)
        self.numaCombo.addItems(['关闭', 'distribute', 'isolate', 'numactl'])
        self.numaCombo.setFixedWidth(CTRL_WIDTH)
        self.numaCard.hBoxLayout.addWidget(self.numaCombo, 0, Qt.AlignRight)
        self.numaCard.hBoxLayout.addSpacing(16)

        self.gpuGroup.addSettingCard(self.nglCard)
        self.gpuGroup.addSettingCard(self.mainGpuCard)
        self.gpuGroup.addSettingCard(self.tsSplitCard)
        self.gpuGroup.addSettingCard(self.nommapCard)
        self.gpuGroup.addSettingCard(self.numaCard)
        self.expandLayout.addWidget(self.gpuGroup)


class ServerInterface(BaseSettingInterface):
    """服务器设置"""

    def __init__(self, parent=None):
        super().__init__('服务器设置', 'server-interface', parent)

        # ─────────── 网络配置 ───────────
        self.netGroup = SettingCardGroup('网络配置', self.scrollWidget)

        # 监听地址 (--host)
        self.hostCard = SettingCard(FIF.GLOBE, '监听地址', '服务器绑定的 IP 地址，0.0.0.0 可从局域网访问', self.netGroup)
        self.hostEdit = LineEdit(self.hostCard)
        self.hostEdit.setText('0.0.0.0')
        self.hostEdit.setFixedWidth(CTRL_WIDTH)
        self.hostCard.hBoxLayout.addWidget(self.hostEdit, 0, Qt.AlignRight)
        self.hostCard.hBoxLayout.addSpacing(16)

        # 端口 (--port)
        self.portCard = SettingCard(FIF.CONNECT, '端口', '服务器监听的端口号（默认 8080）', self.netGroup)
        self.portSpin = SpinBox(self.portCard)
        self.portSpin.setRange(1, 65535)
        self.portSpin.setValue(8080)
        self.portSpin.setFixedWidth(CTRL_WIDTH)
        self.portCard.hBoxLayout.addWidget(self.portSpin, 0, Qt.AlignRight)
        self.portCard.hBoxLayout.addSpacing(16)

        # API 密钥 (--api-key)
        self.apiKeyCard = SettingCard(FIF.VPN, 'API 密钥', '设置后客户端需携带此密钥进行身份验证（留空为无）', self.netGroup)
        self.apiKeyEdit = LineEdit(self.apiKeyCard)
        self.apiKeyEdit.setPlaceholderText('留空则不启用')
        self.apiKeyEdit.setFixedWidth(CTRL_WIDTH)
        self.apiKeyCard.hBoxLayout.addWidget(self.apiKeyEdit, 0, Qt.AlignRight)
        self.apiKeyCard.hBoxLayout.addSpacing(16)

        self.netGroup.addSettingCard(self.hostCard)
        self.netGroup.addSettingCard(self.portCard)
        self.netGroup.addSettingCard(self.apiKeyCard)
        self.expandLayout.addWidget(self.netGroup)

        # ─────────── 性能配置 ───────────
        self.perfGroup = SettingCardGroup('性能配置', self.scrollWidget)

        # 线程数 (--threads)
        self.threadsCard = SettingCard(FIF.SPEED_HIGH, '线程数', 'CPU 推理使用的线程数，-1 为自动检测（默认 -1）', self.perfGroup)
        self.threadsSpin = SpinBox(self.threadsCard)
        self.threadsSpin.setRange(-1, 256)
        self.threadsSpin.setValue(-1)
        self.threadsSpin.setFixedWidth(CTRL_WIDTH)
        self.threadsCard.hBoxLayout.addWidget(self.threadsSpin, 0, Qt.AlignRight)
        self.threadsCard.hBoxLayout.addSpacing(16)

        # 批处理大小 (--batch-size)
        self.batchCard = SettingCard(FIF.SPEED_MEDIUM, '批处理大小', '提示词处理阶段的逻辑批大小，影响首次响应速度（默认 2048）', self.perfGroup)
        self.batchSpin = SpinBox(self.batchCard)
        self.batchSpin.setRange(1, 8192)
        self.batchSpin.setValue(2048)
        self.batchSpin.setFixedWidth(CTRL_WIDTH)
        self.batchCard.hBoxLayout.addWidget(self.batchSpin, 0, Qt.AlignRight)
        self.batchCard.hBoxLayout.addSpacing(16)

        # 微批处理大小 (--ubatch-size)
        self.ubatchCard = SettingCard(FIF.SPEED_OFF, '微批处理大小', '更细粒度的批处理控制（默认 512）', self.perfGroup)
        self.ubatchSpin = SpinBox(self.ubatchCard)
        self.ubatchSpin.setRange(1, 8192)
        self.ubatchSpin.setValue(512)
        self.ubatchSpin.setFixedWidth(CTRL_WIDTH)
        self.ubatchCard.hBoxLayout.addWidget(self.ubatchSpin, 0, Qt.AlignRight)
        self.ubatchCard.hBoxLayout.addSpacing(16)

        # 并行序列数 (--parallel)
        self.parallelCard = SettingCard(FIF.SYNC, '并行序列数', '服务器最大并发 slot 数量，-1 为自动（默认 -1）', self.perfGroup)
        self.parallelSpin = SpinBox(self.parallelCard)
        self.parallelSpin.setRange(-1, 128)
        self.parallelSpin.setValue(-1)
        self.parallelSpin.setFixedWidth(CTRL_WIDTH)
        self.parallelCard.hBoxLayout.addWidget(self.parallelSpin, 0, Qt.AlignRight)
        self.parallelCard.hBoxLayout.addSpacing(16)

        # 超时时间 (--timeout)
        self.timeoutCard = SettingCard(FIF.HISTORY, '超时时间', '服务器超时，单位秒（默认 600）', self.perfGroup)
        self.timeoutSpin = SpinBox(self.timeoutCard)
        self.timeoutSpin.setRange(0, 99999)
        self.timeoutSpin.setValue(600)
        self.timeoutSpin.setFixedWidth(CTRL_WIDTH)
        self.timeoutCard.hBoxLayout.addWidget(self.timeoutSpin, 0, Qt.AlignRight)
        self.timeoutCard.hBoxLayout.addSpacing(16)

        self.perfGroup.addSettingCard(self.threadsCard)
        self.perfGroup.addSettingCard(self.batchCard)
        self.perfGroup.addSettingCard(self.ubatchCard)
        self.perfGroup.addSettingCard(self.parallelCard)
        self.perfGroup.addSettingCard(self.timeoutCard)
        self.expandLayout.addWidget(self.perfGroup)

        # ─────────── 功能开关 ───────────
        self.toggleGroup = SettingCardGroup('功能开关', self.scrollWidget)

        # 详细输出 (--verbose)
        self.verboseCard = SettingCard(FIF.VIEW, '详细输出', '启用详细日志输出，方便调试', self.toggleGroup)
        self.verboseCombo = FixedComboBox(self.verboseCard)
        self.verboseCombo.addItems(['关闭', '启用'])
        self.verboseCombo.setFixedWidth(CTRL_WIDTH)
        self.verboseCard.hBoxLayout.addWidget(self.verboseCombo, 0, Qt.AlignRight)
        self.verboseCard.hBoxLayout.addSpacing(16)

        # 监控指标 (--metrics)
        self.metricsCard = SettingCard(FIF.DEVELOPER_TOOLS, '监控指标', '启用 Prometheus 格式的性能监控端点', self.toggleGroup)
        self.metricsCombo = FixedComboBox(self.metricsCard)
        self.metricsCombo.addItems(['关闭', '启用'])
        self.metricsCombo.setFixedWidth(CTRL_WIDTH)
        self.metricsCard.hBoxLayout.addWidget(self.metricsCombo, 0, Qt.AlignRight)
        self.metricsCard.hBoxLayout.addSpacing(16)

        # 禁用 Web 界面 (--no-webui)
        self.webuiCard = SettingCard(FIF.GLOBE, 'Web 界面', '内置的 Web 聊天界面', self.toggleGroup)
        self.webuiCombo = FixedComboBox(self.webuiCard)
        self.webuiCombo.addItems(['启用', '禁用'])
        self.webuiCombo.setFixedWidth(CTRL_WIDTH)
        self.webuiCard.hBoxLayout.addWidget(self.webuiCombo, 0, Qt.AlignRight)
        self.webuiCard.hBoxLayout.addSpacing(16)

        self.toggleGroup.addSettingCard(self.verboseCard)
        self.toggleGroup.addSettingCard(self.metricsCard)
        self.toggleGroup.addSettingCard(self.webuiCard)
        self.expandLayout.addWidget(self.toggleGroup)


_ANSI_RE = re.compile(r'\x1b\[[\?>=]*[0-9;]*[a-zA-Z~@`]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\([A-Z]|\x1b[=>]')


class TerminalWorker(QThread):
    """后台线程：通过 subprocess 读取进程输出"""
    dataReady = Signal(str)
    processFinished = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._command = ''
        self._process = None

    def start_process(self, command):
        self._command = command
        self.start()

    def run(self):
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            self._process = subprocess.Popen(self._command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE, startupinfo=si, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            while True:
                raw = self._process.stdout.read1(4096)
                if not raw:
                    break
                if b'\x00' in raw:
                    text = raw.decode('utf-16-le', errors='replace')
                else:
                    text = raw.decode('utf-8', errors='replace')
                if text:
                    self.dataReady.emit(text)
            self._process.wait()
            self.processFinished.emit(self._process.returncode)
        except Exception as e:
            self.dataReady.emit(f'\n--- 启动失败: {e} ---\n')
            self.processFinished.emit(-1)

    def write(self, data):
        if self._process and self._process.poll() is None and self._process.stdin:
            try:
                self._process.stdin.write(data.encode('utf-8'))
                self._process.stdin.flush()
            except Exception:
                pass

    def stop(self):
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    self._process.kill()
                except Exception:
                    pass


class TerminalTextEdit(QPlainTextEdit):
    """终端文本控件，拦截键盘输入并转发到 pty"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        font = QFont('Consolas', 11)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setStyleSheet('QPlainTextEdit { background-color: #1e1e1e; color: #cccccc; border: 1px solid #333333; border-radius: 4px; padding: 8px; selection-background-color: #264f78; }')

    def keyPressEvent(self, event):
        if not self.worker:
            return
        key = event.key()
        modifiers = event.modifiers()
        if modifiers & Qt.ControlModifier:
            code = key - Qt.Key_A + 1
            if 1 <= code <= 26:
                self.worker.write(chr(code))
            return
        key_map = {
            Qt.Key_Return: '\r', Qt.Key_Enter: '\r',
            Qt.Key_Backspace: '\x7f', Qt.Key_Tab: '\t', Qt.Key_Escape: '\x1b',
            Qt.Key_Up: '\x1b[A', Qt.Key_Down: '\x1b[B',
            Qt.Key_Right: '\x1b[C', Qt.Key_Left: '\x1b[D',
            Qt.Key_Home: '\x1b[H', Qt.Key_End: '\x1b[F',
            Qt.Key_Delete: '\x1b[3~', Qt.Key_Insert: '\x1b[2~',
            Qt.Key_PageUp: '\x1b[5~', Qt.Key_PageDown: '\x1b[6~',
        }
        if key in key_map:
            self.worker.write(key_map[key])
        elif event.text():
            self.worker.write(event.text())


class LogInterface(QWidget):
    """运行日志界面（嵌入终端模拟器）"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('log-interface')
        self.worker = None

        mainLayout = QVBoxLayout(self)
        mainLayout.setContentsMargins(36, 20, 36, 20)
        mainLayout.setSpacing(12)

        self.titleLabel = QLabel('终端', self)
        self.titleLabel.setStyleSheet('font: 33px "Segoe UI", "Microsoft YaHei"; background: transparent;')
        mainLayout.addWidget(self.titleLabel)

        self.logText = TerminalTextEdit(self)
        mainLayout.addWidget(self.logText, 1)

        btnLayout = QHBoxLayout()
        btnLayout.setSpacing(12)
        self.launchBtn = PrimaryPushButton(FIF.PLAY, '启动', self)
        self.launchBtn.setFixedHeight(40)
        btnLayout.addWidget(self.launchBtn)
        self.stopBtn = PushButton(FIF.CLOSE, '停止', self)
        self.stopBtn.setFixedHeight(40)
        self.stopBtn.setEnabled(False)
        self.stopBtn.clicked.connect(self.stopProcess)
        btnLayout.addWidget(self.stopBtn)
        self.clearBtn = PushButton(FIF.DELETE, '清空', self)
        self.clearBtn.setFixedHeight(40)
        self.clearBtn.clicked.connect(lambda: self.logText.clear())
        btnLayout.addWidget(self.clearBtn)
        mainLayout.addLayout(btnLayout)

    def launchCommand(self, command):
        """通过 pywinpty 启动命令"""
        if self.worker and self.worker.isRunning():
            InfoBar.warning(title='进程正在运行', content='请先停止当前进程', orient=Qt.Horizontal, isClosable=False, position=InfoBarPosition.TOP, duration=2000, parent=self.window())
            return
        self.logText.clear()
        self.worker = TerminalWorker(self)
        self.worker.dataReady.connect(self._appendOutput)
        self.worker.processFinished.connect(self._onProcessFinished)
        self.logText.worker = self.worker
        self.worker.start_process(command)
        self.launchBtn.setEnabled(False)
        self.stopBtn.setEnabled(True)
        self.logText.setFocus()

    def _appendOutput(self, text):
        text = _ANSI_RE.sub('', text)
        text = text.replace('\r\n', '\n')
        text = text.replace('\r', '\n')
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
        text = re.sub(r'\n{2,}', '\n', text)
        if not text:
            return
        cursor = self.logText.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.logText.setTextCursor(cursor)
        self.logText.ensureCursorVisible()

    def _onProcessFinished(self, exit_code):
        cursor = self.logText.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f'\n--- 进程已退出 (exit code: {exit_code}) ---\n')
        self.logText.setTextCursor(cursor)
        self.logText.ensureCursorVisible()
        self.launchBtn.setEnabled(True)
        self.stopBtn.setEnabled(False)
        self.logText.worker = None

    def stopProcess(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()


class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__()

        llm_models, mm_models = loadModels()
        self.basicInterface = BasicInterface(self)
        self.modelInterface = ModelInterface(llm_models, mm_models, self)
        self.serverInterface = ServerInterface(self)
        self.logInterface = LogInterface(self)

        self.initNavigation()
        self.initWindow()
        self._connectAllSignals()
        self._loadConfig()
        self._updateCommandPreview()
        self.logInterface.launchBtn.clicked.connect(self._onLaunch)
        self.basicInterface.runBtn.clicked.connect(self._onRunBtnClicked)

    def initNavigation(self):
        self.addSubInterface(self.basicInterface, FIF.HOME, '基础设置')
        self.addSubInterface(self.modelInterface, FIF.IOT, '模型设置')
        self.addSubInterface(self.serverInterface, FIF.WIFI, '服务器设置')
        self.addSubInterface(self.logInterface, FIF.COMMAND_PROMPT, '运行日志')

    def initWindow(self):
        self.resize(900, 700)
        self.setWindowTitle('llama.cpp 启动器')
        self.setWindowIcon(QIcon(':/qfluentwidgets/images/logo.png'))
        desktop = QApplication.screens()[0].availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

    def buildCommand(self):
        """汇总所有页面的参数，构建 WSL 启动命令"""
        mi = self.modelInterface
        si = self.serverInterface
        parts = ['wsl', self.basicInterface.execPathEdit.text().strip()]

        # 模型选择（用实际路径替换显示名）
        llm = mi.llmCombo.currentText()
        if llm and llm in mi.llmPaths:
            parts.extend(['-m', mi.llmPaths[llm]])

        mm = mi.mmCombo.currentText()
        if mm and mm != '无' and mm in mi.mmPaths:
            parts.extend(['-mm', mi.mmPaths[mm]])

        # 模型参数
        ctx_text = mi.ctxEdit.text().strip()
        if ctx_text:
            parts.extend(['-c', str(int(ctx_text) * 1000)])

        predict = mi.predictEdit.text().strip()
        if predict:
            parts.extend(['-n', predict])

        parts.extend(['--temp', f'{mi.tempSpin.value():.2f}'])
        parts.extend(['--top-p', f'{mi.topPSpin.value():.2f}'])
        parts.extend(['--top-k', str(mi.topKSpin.value())])
        parts.extend(['--repeat-penalty', f'{mi.repeatPenaltySpin.value():.2f}'])
        parts.extend(['--repeat-last-n', str(mi.repeatLastNSpin.value())])

        # KV 缓存
        parts.extend(['--cache-type-k', mi.cacheKCombo.currentText()])
        parts.extend(['--cache-type-v', mi.cacheVCombo.currentText()])

        cache_ram = mi.cacheRamEdit.text().strip()
        if cache_ram:
            parts.extend(['--cache-ram', cache_ram])

        parts.extend(['--flash-attn', mi.faCombo.currentText()])

        # 多模态参数
        if mm and mm != '无':
            img_max = mi.imgMaxEdit.text().strip()
            if img_max:
                parts.extend(['--image-max-tokens', img_max])
            img_min = mi.imgMinEdit.text().strip()
            if img_min:
                parts.extend(['--image-min-tokens', img_min])

        # GPU 加速
        parts.extend(['-ngl', str(mi.nglSpin.value())])
        if mi.mainGpuSpin.value() != 0:
            parts.extend(['-mg', str(mi.mainGpuSpin.value())])
        ts = mi.tsSplitEdit.text().strip()
        if ts:
            parts.extend(['-ts', ts])
        if mi.nommapCombo.currentText() == '启用':
            parts.append('--no-mmap')
        numa = mi.numaCombo.currentText()
        if numa != '关闭':
            parts.extend(['--numa', numa])

        # 服务器 - 网络
        parts.extend(['--host', si.hostEdit.text().strip()])
        parts.extend(['--port', str(si.portSpin.value())])

        api_key = si.apiKeyEdit.text().strip()
        if api_key:
            parts.extend(['--api-key', api_key])

        # 服务器 - 性能
        parts.extend(['--threads', str(si.threadsSpin.value())])
        parts.extend(['--batch-size', str(si.batchSpin.value())])
        parts.extend(['--ubatch-size', str(si.ubatchSpin.value())])
        parts.extend(['--parallel', str(si.parallelSpin.value())])
        parts.extend(['--timeout', str(si.timeoutSpin.value())])

        # 服务器 - 功能开关
        if si.verboseCombo.currentText() == '启用':
            parts.append('--verbose')
        if si.metricsCombo.currentText() == '启用':
            parts.append('--metrics')
        if si.webuiCombo.currentText() == '禁用':
            parts.append('--no-webui')

        return ' '.join(parts)

    def _updateCommandPreview(self):
        self.basicInterface.cmdPreview.setText(self.buildCommand())

    def _connectAllSignals(self):
        """连接所有控件的信号，实时更新命令预览"""
        bi = self.basicInterface
        mi = self.modelInterface
        si = self.serverInterface

        bi.execPathEdit.textChanged.connect(self._updateCommandPreview)

        mi.llmCombo.currentIndexChanged.connect(self._updateCommandPreview)
        mi.mmCombo.currentIndexChanged.connect(self._updateCommandPreview)
        mi.ctxEdit.textChanged.connect(self._updateCommandPreview)
        mi.predictEdit.textChanged.connect(self._updateCommandPreview)
        mi.tempSpin.valueChanged.connect(self._updateCommandPreview)
        mi.topPSpin.valueChanged.connect(self._updateCommandPreview)
        mi.topKSpin.valueChanged.connect(self._updateCommandPreview)
        mi.repeatPenaltySpin.valueChanged.connect(self._updateCommandPreview)
        mi.repeatLastNSpin.valueChanged.connect(self._updateCommandPreview)
        mi.cacheKCombo.currentIndexChanged.connect(self._updateCommandPreview)
        mi.cacheVCombo.currentIndexChanged.connect(self._updateCommandPreview)
        mi.cacheRamEdit.textChanged.connect(self._updateCommandPreview)
        mi.faCombo.currentIndexChanged.connect(self._updateCommandPreview)
        mi.imgMaxEdit.textChanged.connect(self._updateCommandPreview)
        mi.imgMinEdit.textChanged.connect(self._updateCommandPreview)
        mi.nglSpin.valueChanged.connect(self._updateCommandPreview)
        mi.mainGpuSpin.valueChanged.connect(self._updateCommandPreview)
        mi.tsSplitEdit.textChanged.connect(self._updateCommandPreview)
        mi.nommapCombo.currentIndexChanged.connect(self._updateCommandPreview)
        mi.numaCombo.currentIndexChanged.connect(self._updateCommandPreview)

        si.hostEdit.textChanged.connect(self._updateCommandPreview)
        si.portSpin.valueChanged.connect(self._updateCommandPreview)
        si.apiKeyEdit.textChanged.connect(self._updateCommandPreview)
        si.threadsSpin.valueChanged.connect(self._updateCommandPreview)
        si.batchSpin.valueChanged.connect(self._updateCommandPreview)
        si.ubatchSpin.valueChanged.connect(self._updateCommandPreview)
        si.parallelSpin.valueChanged.connect(self._updateCommandPreview)
        si.timeoutSpin.valueChanged.connect(self._updateCommandPreview)
        si.verboseCombo.currentIndexChanged.connect(self._updateCommandPreview)
        si.metricsCombo.currentIndexChanged.connect(self._updateCommandPreview)
        si.webuiCombo.currentIndexChanged.connect(self._updateCommandPreview)

    def _onLaunch(self):
        self._updateCommandPreview()
        cmd = self.buildCommand()
        self.logInterface.launchCommand(cmd)

    def _onRunBtnClicked(self):
        self.switchTo(self.logInterface)
        self._onLaunch()

    # ─────────── 配置持久化 ───────────

    def _configPath(self):
        return os.path.join(BASE_DIR, 'config.json')

    def _saveConfig(self):
        bi = self.basicInterface
        mi = self.modelInterface
        si = self.serverInterface
        cfg = {
            'exec_path': bi.execPathEdit.text(),
            'llm_model': mi.llmCombo.currentText(),
            'mm_model': mi.mmCombo.currentText(),
            'ctx_length': mi.ctxEdit.text(),
            'predict_length': mi.predictEdit.text(),
            'temperature': mi.tempSpin.value(),
            'top_p': mi.topPSpin.value(),
            'top_k': mi.topKSpin.value(),
            'repeat_penalty': mi.repeatPenaltySpin.value(),
            'repeat_last_n': mi.repeatLastNSpin.value(),
            'cache_type_k': mi.cacheKCombo.currentText(),
            'cache_type_v': mi.cacheVCombo.currentText(),
            'cache_ram': mi.cacheRamEdit.text(),
            'flash_attention': mi.faCombo.currentText(),
            'image_max_tokens': mi.imgMaxEdit.text(),
            'image_min_tokens': mi.imgMinEdit.text(),
            'ngl': mi.nglSpin.value(),
            'main_gpu': mi.mainGpuSpin.value(),
            'tensor_split': mi.tsSplitEdit.text(),
            'nommap': mi.nommapCombo.currentText(),
            'numa': mi.numaCombo.currentText(),
            'host': si.hostEdit.text(),
            'port': si.portSpin.value(),
            'api_key': si.apiKeyEdit.text(),
            'threads': si.threadsSpin.value(),
            'batch_size': si.batchSpin.value(),
            'ubatch_size': si.ubatchSpin.value(),
            'parallel': si.parallelSpin.value(),
            'timeout': si.timeoutSpin.value(),
            'verbose': si.verboseCombo.currentText(),
            'metrics': si.metricsCombo.currentText(),
            'webui': si.webuiCombo.currentText(),
        }
        try:
            with open(self._configPath(), 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _loadConfig(self):
        path = self._configPath()
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception:
            return
        bi = self.basicInterface
        mi = self.modelInterface
        si = self.serverInterface
        bi.execPathEdit.setText(cfg.get('exec_path', bi.execPathEdit.text()))
        mi.llmCombo.setCurrentText(cfg.get('llm_model', mi.llmCombo.currentText()))
        mi.mmCombo.setCurrentText(cfg.get('mm_model', mi.mmCombo.currentText()))
        mi.ctxEdit.setText(cfg.get('ctx_length', mi.ctxEdit.text()))
        mi.predictEdit.setText(cfg.get('predict_length', mi.predictEdit.text()))
        mi.tempSpin.setValue(cfg.get('temperature', mi.tempSpin.value()))
        mi.topPSpin.setValue(cfg.get('top_p', mi.topPSpin.value()))
        mi.topKSpin.setValue(cfg.get('top_k', mi.topKSpin.value()))
        mi.repeatPenaltySpin.setValue(cfg.get('repeat_penalty', mi.repeatPenaltySpin.value()))
        mi.repeatLastNSpin.setValue(cfg.get('repeat_last_n', mi.repeatLastNSpin.value()))
        mi.cacheKCombo.setCurrentText(cfg.get('cache_type_k', mi.cacheKCombo.currentText()))
        mi.cacheVCombo.setCurrentText(cfg.get('cache_type_v', mi.cacheVCombo.currentText()))
        mi.cacheRamEdit.setText(cfg.get('cache_ram', mi.cacheRamEdit.text()))
        mi.faCombo.setCurrentText(cfg.get('flash_attention', mi.faCombo.currentText()))
        mi.imgMaxEdit.setText(cfg.get('image_max_tokens', mi.imgMaxEdit.text()))
        mi.imgMinEdit.setText(cfg.get('image_min_tokens', mi.imgMinEdit.text()))
        mi.nglSpin.setValue(cfg.get('ngl', mi.nglSpin.value()))
        mi.mainGpuSpin.setValue(cfg.get('main_gpu', mi.mainGpuSpin.value()))
        mi.tsSplitEdit.setText(cfg.get('tensor_split', mi.tsSplitEdit.text()))
        mi.nommapCombo.setCurrentText(cfg.get('nommap', mi.nommapCombo.currentText()))
        mi.numaCombo.setCurrentText(cfg.get('numa', mi.numaCombo.currentText()))
        si.hostEdit.setText(cfg.get('host', si.hostEdit.text()))
        si.portSpin.setValue(cfg.get('port', si.portSpin.value()))
        si.apiKeyEdit.setText(cfg.get('api_key', si.apiKeyEdit.text()))
        si.threadsSpin.setValue(cfg.get('threads', si.threadsSpin.value()))
        si.batchSpin.setValue(cfg.get('batch_size', si.batchSpin.value()))
        si.ubatchSpin.setValue(cfg.get('ubatch_size', si.ubatchSpin.value()))
        si.parallelSpin.setValue(cfg.get('parallel', si.parallelSpin.value()))
        si.timeoutSpin.setValue(cfg.get('timeout', si.timeoutSpin.value()))
        si.verboseCombo.setCurrentText(cfg.get('verbose', si.verboseCombo.currentText()))
        si.metricsCombo.setCurrentText(cfg.get('metrics', si.metricsCombo.currentText()))
        si.webuiCombo.setCurrentText(cfg.get('webui', si.webuiCombo.currentText()))

    def closeEvent(self, event):
        self._saveConfig()
        super().closeEvent(event)


if __name__ == '__main__':
    setTheme(Theme.DARK)
    w = MainWindow()
    w.show()
    app.exec()
