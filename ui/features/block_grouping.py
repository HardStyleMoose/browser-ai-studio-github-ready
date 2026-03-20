from PySide6.QtWidgets import QGraphicsItemGroup

class BlockGroupingManager:
    def __init__(self, scene):
        self.scene = scene
        self.groups = []

    def group_blocks(self, blocks):
        group = QGraphicsItemGroup()
        for block in blocks:
            group.addToGroup(block)
        self.scene.addItem(group)
        self.groups.append(group)
        return group

    def ungroup_blocks(self, group):
        for item in group.childItems():
            group.removeFromGroup(item)
        self.scene.removeItem(group)
        self.groups.remove(group)
