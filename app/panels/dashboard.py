from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class DashboardPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("<b>AI Lab Dashboard</b>")
        title.setStyleSheet("font-size:18px;padding:8px;")
        layout.addWidget(title)

        # Chart placeholder (training progress)
        from PySide6.QtCharts import QChart, QChartView, QLineSeries
        chart = QChart()
        chart.setTitle("Training Progress")
        series = QLineSeries()
        # Example data
        for i in range(10):
            series.append(i, i * (i % 3 + 1))
        chart.addSeries(series)
        chart.createDefaultAxes()
        chart_view = QChartView(chart)
        chart_view.setMinimumHeight(200)
        layout.addWidget(chart_view)

        # Status widgets
        reward_label = QLabel("Current Reward: <b>0.0</b>")
        reward_label.setStyleSheet("font-size:14px;padding:4px;")
        layout.addWidget(reward_label)

        episode_label = QLabel("Episode: <b>1</b>")
        episode_label.setStyleSheet("font-size:14px;padding:4px;")
        layout.addWidget(episode_label)

        self.setLayout(layout)
