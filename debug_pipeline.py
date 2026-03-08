import asyncio
from core.pipeline import HSPipeline

async def run():
    pipeline = HSPipeline()
    
    def cb(data):
        print(f"[{data.get('type')}] {data.get('message', '')}")
        if data.get('type') in ['fast_path_result', 'slow_path_result']:
            print(f"RESULT: {data.get('data')}")

    try:
        res = pipeline.classify("da cá sấu thô", stream_callback=cb)
        print(f"\nFINAL OUTPUT:\n{res}")
    except Exception as e:
        print(f"ERROR: {e}")

asyncio.run(run())
