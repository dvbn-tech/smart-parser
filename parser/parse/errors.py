class InvalidResponse(Exception):
    """Ответ не проходит схему: обязательное поле не найдено или неверного типа.

    Такой ответ ничего не пишет в базу; задача падает без повторов (техспека §6).
    """

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason
