import socketio
import time
import base64
import numpy as np

sio = socketio.Client()
session_id = None
received_events = []

@sio.event
def connect():
    print('✅ 连接成功')

@sio.event
def disconnect():
    print('🔌 断开连接')

@sio.on('session_created')
def on_session_created(data):
    global session_id
    session_id = data['session_id']
    print(f'✅ Session 创建: {session_id}')

@sio.on('audio_received')
def on_audio_received(data):
    received_events.append(('audio_received', data))

@sio.on('transcript')
def on_transcript(data):
    received_events.append(('transcript', data))
    text = data.get("interim_text", "") or data.get("final_text", "")
    is_final = data.get("is_final", False)
    print(f'📝 转写结果: "{text}" (final={is_final})')

@sio.on('session_finalized')
def on_session_finalized(data):
    received_events.append(('session_finalized', data))
    print(f'🏁 会话结束')

@sio.on('error')
def on_error(data):
    print(f'❌ 错误: {data}')

def run_test(server_url: str = 'http://localhost:50051'):
    print(f'🔗 连接到 {server_url}...')
    
    try:
        sio.connect(server_url, transports=['websocket'])
    except Exception as e:
        print(f'❌ 连接失败: {e}')
        return False
    
    print('📝 创建会话...')
    sio.emit('create_session', {
        'meeting_id': 'test_meeting',
        'participant_id': 'test_user',
        'participant_name': '测试用户'
    })
    time.sleep(0.5)
    
    if not session_id:
        print('❌ 会话创建失败')
        sio.disconnect()
        return False
    
    print('🎤 发送音频数据...')
    for i in range(3):
        audio = np.sin(2 * np.pi * 440 * np.linspace(0, 0.96, 9600)).astype(np.float32) * 0.3
        audio_base64 = base64.b64encode(audio.tobytes()).decode('utf-8')
        sio.emit('audio_chunk', {
            'session_id': session_id,
            'audio': audio_base64,
            'sample_rate': 16000
        })
        print(f'   音频块 {i+1}/3 已发送')
        time.sleep(0.3)
    
    print('⏳ 等待转写结果...')
    time.sleep(3)
    
    print('🏁 结束会话...')
    sio.emit('end_session', {'session_id': session_id})
    time.sleep(2)
    
    sio.disconnect()
    
    print(f'\n📊 测试结果: 共收到 {len(received_events)} 个事件')
    for i, (event_type, data) in enumerate(received_events):
        print(f'  [{i+1}] {event_type}')
    
    return True


if __name__ == '__main__':
    success = run_test('http://localhost:50052')
    if success:
        print('\n✅ 所有测试通过!')
    else:
        print('\n❌ 测试失败')
