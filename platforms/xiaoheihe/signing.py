import hashlib
import random
import time


class RequestSigner:
    """生成小黑盒接口所需的时间戳、随机数和 hkey。"""

    CHAR_TABLE = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"

    def sign_path(self, path: str) -> dict[str, str | int]:
        now = int(time.time())
        nonce = (
            hashlib.md5((str(now) + str(random.random())).encode()).hexdigest().upper()
        )
        return {
            "hkey": self.ov(path, now + 1, nonce),
            "_time": now,
            "nonce": nonce,
        }

    def ov(self, path: str, timestamp: int, nonce: str) -> str:
        normalized_path = "/" + "/".join(part for part in path.split("/") if part) + "/"
        interleaved = self.interleave(
            [
                self.av(str(timestamp), -2),
                self.sv(normalized_path),
                self.sv(nonce),
            ]
        )[:20]
        digest = hashlib.md5(interleaved.encode()).hexdigest()
        prefix = self.av(digest[:5], -4)
        suffix = str(
            sum(self.mix_columns([ord(character) for character in digest[-6:]])) % 100
        ).zfill(2)
        return prefix + suffix

    def av(self, text: str, cut: int) -> str:
        table = self.CHAR_TABLE[:cut]
        return "".join(table[ord(character) % len(table)] for character in text)

    def sv(self, text: str) -> str:
        return "".join(
            self.CHAR_TABLE[ord(character) % len(self.CHAR_TABLE)] for character in text
        )

    @staticmethod
    def interleave(parts: list[str]) -> str:
        result = []
        for index in range(max(len(part) for part in parts)):
            for part in parts:
                if index < len(part):
                    result.append(part[index])
        return "".join(result)

    @staticmethod
    def xtime(value: int) -> int:
        return ((value << 1) ^ 27) & 0xFF if value & 128 else value << 1

    @classmethod
    def mul3(cls, value: int) -> int:
        return cls.xtime(value) ^ value

    @classmethod
    def mul6(cls, value: int) -> int:
        return cls.mul3(cls.xtime(value))

    @classmethod
    def mul12(cls, value: int) -> int:
        return cls.mul6(cls.mul3(cls.xtime(value)))

    @classmethod
    def mul14(cls, value: int) -> int:
        return cls.mul12(value) ^ cls.mul6(value) ^ cls.mul3(value)

    @classmethod
    def mix_columns(cls, column: list[int]) -> list[int]:
        values = list(column)
        while len(values) < 4:
            values.append(0)
        mixed = [
            cls.mul14(values[0])
            ^ cls.mul12(values[1])
            ^ cls.mul6(values[2])
            ^ cls.mul3(values[3]),
            cls.mul3(values[0])
            ^ cls.mul14(values[1])
            ^ cls.mul12(values[2])
            ^ cls.mul6(values[3]),
            cls.mul6(values[0])
            ^ cls.mul3(values[1])
            ^ cls.mul14(values[2])
            ^ cls.mul12(values[3]),
            cls.mul12(values[0])
            ^ cls.mul6(values[1])
            ^ cls.mul3(values[2])
            ^ cls.mul14(values[3]),
        ]
        if len(values) > 4:
            mixed.extend(values[4:])
        return mixed
