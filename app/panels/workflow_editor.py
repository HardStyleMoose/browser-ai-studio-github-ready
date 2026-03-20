from PySide6.QtWidgets import QWidget, QVBoxLayout
from NodeGraphQt import NodeGraph

class WorkflowEditorPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        # NodeGraph widget
        self.graph = NodeGraph()
        self.graph_widget = self.graph.widget
        layout.addWidget(self.graph_widget)

        # Visual cues and legend
        legend = QLabel("<b>Node Editor Legend:</b> Action, Condition, Sequence, Selector, Loop")
        legend.setStyleSheet("color:#f8fafc;background:#0f172a;padding:4px;")
        layout.addWidget(legend)

        # Toolbar placeholder
        toolbar = QLabel("Toolbar: [Add Node] [Delete Node] [Connect] [Undo] [Redo]")
        toolbar.setStyleSheet("color:#cbd5e1;background:#334155;padding:4px;")
        layout.addWidget(toolbar)

        self.setLayout(layout)
        self.setStyleSheet("background-color: #222;")