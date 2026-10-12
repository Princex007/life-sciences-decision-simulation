"""Forecast plugin registry."""
class ForecastRegistry:
    def __init__(self):
        self._models = {}
    def register(self, model_id, model):
        self._models[model_id] = model
    def get(self, model_id):
        try:
            return self._models[model_id]
        except KeyError as error:
            raise ValueError(f"Forecast model is not registered: {model_id}") from error
