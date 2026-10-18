from datetime import datetime

from ubento.formatting import ago, compact, money, number, pct, split_money


def test_number_uses_brazilian_separators():
    assert number(1234.5) == "1.234,50"
    assert number(-0.126, 3) == "-0,126"


def test_money_and_split():
    assert money(7223.62) == "$7.223,62"
    assert split_money(11940.43) == ("$11.940", ",43")
    assert money(-5) == "-$5,00"


def test_compact_and_pct():
    assert compact(1240) == "$1,2K"
    assert compact(525) == "$525"
    assert pct(14.31) == "14,3%"
    assert pct(-0.03) == "0,03%"


def test_ago():
    now = datetime(2026, 10, 18, 15, 0)
    assert ago(datetime(2026, 10, 18, 14, 59, 40), now) == "Agora"
    assert ago(datetime(2026, 10, 18, 14, 30), now) == "há 30 min"
    assert ago(datetime(2026, 10, 18, 12, 0), now) == "há 3 h"
    assert ago(datetime(2026, 10, 17, 9, 0), now) == "Ontem"
    assert ago(datetime(2026, 10, 10, 9, 0), now) == "10 out"
