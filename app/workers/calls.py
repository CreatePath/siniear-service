"""명시적으로 실행하는 단일 주기. 반복 실행은 운영 스케줄러가 담당한다."""

from app.db.session import get_engine
from app.integrations.call_server import send
from app.modules.calls.scheduler import tick
from app.workers.outbox import deliver_one


def run():
    engine = get_engine()
    tick(engine)
    for _ in range(100):
        if not deliver_one(engine, "C", send):
            break


if __name__ == "__main__":
    run()
