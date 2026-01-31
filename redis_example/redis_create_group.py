import redis

r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

STREAM_KEY = "mystream"
GROUP = "mygroup"

try:
    # id="$" 의미 : 지금 이 순간 스트림의 끝
    # 그룹을 만들고 나서 XREADGROUP로 읽으면 그 시점 이후에
    # 새로 들어오는 메시지부터 받게 됨
    # id="0-0" 처음부터(과거 전부 포함) 읽기 시작

    # mkstream=True
    # 스트림 키가 아직 존재하지 않아도 컨슈머
    # 그룹을 만들 수 있게 해주는 옵션
    r.xgroup_create(STREAM_KEY, GROUP, id="$", mkstream=True)
    print("Group created")
except redis.exceptions.ResponseError as e:
    print(e)