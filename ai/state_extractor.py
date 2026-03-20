from ai.state_utils import extract_numeric_state

class StateExtractor:
    def extract(self, text):
        return extract_numeric_state(text)
