Warning: truncated output (original token count: 84528)
Total output lines: 2433

# �����¼

## 2026-09-14 �� PR #120 governance incident record

- PR #120 �ѽ��� `main`���� merge authorization û�б� durable evidence ֤����
- `PR120_MERGE_AUTHORIZATION = NOT_PROVEN`��
- `PRODUCTION_PROMOTION_AUTHORIZATION = NO`��ֱ�� Production Owner ������� adjudication��
- Research harness��PIT/Replay/Holdout��Registry �� capture ����������δ����׼�� production routing �� runtime semantic changes ִ�� selective restoration��
- Merged code ������ retrospective authorization��

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> For user-friendly release highlights, see the [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) page.

## [Unreleased]

- Add a separate OpenD extended-hours callback panel. The service requests Session.ALL and exposes a bounded, sanitized latest forming observation with receipt age and `UNPROVEN` closure; canonical closed bars and Radar admission remain unchanged.

- [�Ľ�] Operations ����̨����ֻ�� OpenD canonical cache ��أ�չʾ��Դ��ʱ�䡢���ʶȡ���ȡ��ʱ������ OHLCV�������� Radar BLOCKED��Live Trade �رա�

- [�Ľ�] STOCK RAZOR �細��ͬ�� V1.4.1 �����̶� GitHub ������������ `#924/6269031171`��һ��ֱ�����ٷ��ֵ�ǰȥ�������¼�������������� PR ��ʷ��ȴ� AWS Actions �Ŷӣ���Ҫ�����ɵ�ǰ���Ӵ���ͬ��д�� append-only �¼���̶�ָ�벢������֤��˽������ȫ�Ĳ��ϴ������ֿ⡣

- [�¹���] STOCK RAZOR V1.4 �����ԡ�����/�״�/OpenD/TickFlow/���ԡ��ȹؼ��ʴ����Ŀ細�ڿ���������Ԥ��ȡ�� OWNER ȥ�������¼�������ר�� GitHub issue_comment �������� #924 �ṹ�����¾� AWS SSM д������ Context Manager����������/ʱ��/��ԴУ�鼰��Ӧ�ع飻��ʵ�������ƶ˵���;������Զ���������������ա�

- [�Ľ�] Self-Improvement V1.3 Ҫ������ STOCK RAZOR ���д����ȹ���������֪��Ӣͬ����ϼ��ڽӰ������پ����Ƿ����ԣ������û��ظ����ѵ����󣬵�����֢״����֤����ͬ����δ֪�¹ʱ�����������¼�����ع���֤���������ü��䡣

- [�¹���] Self-Improvement V1.2 �Զ���¼ Engineering Autonomy δ֪�˳����������ָ�Ʋ���ֹͬ������äĿ���ԣ�ͬʱ�� GitHub CI / Research Radar Tests ʧ�ܺ�ͨ��ֻ�� workflow_run �����쳣��������� 30 �� Actions artifact ���細�ڼ����������Զ��޸������õǼ��������֤�ݺ��ܱ������� PR������/����/֪ͨȨ�޲��ı䡣

- [�Ľ�] Self-Improvement V1.1 Ϊ�細���빤����������������̹�������ժҪ��`--brief`������ȷ���� SHA У�飻Engineering Autonomy 120m �� DeepSeek Coding �Ե���ִ������/����ģ�͵���ǰ��Ϲ������ߺ�ʧЧ����Ǽǡ�����ʱ���Ա���ʵ�⣬�ƶ�ʵ��/����/֪ͨ�ʸ��������ա�

- [�¹���] ���� STOCK RAZOR Self-Improvement V1.0 �ֿ⼶�細�ڼ��ܡ���ǰ main ��������ǩ���Ǽǡ���ͬ SHA/�����ظ�������Ϲ��ߺͱ��뾭���� ai-governance ��飻ֻ�Զ�ȡ GitHub �������ߵĹ���������Ч������������δ�򿪵Ķ������������¹����಻�ı佻�װ�ȫ�Ž���

- [�¹���] �����ƶ� OpenD ���� GitHub XNYS ����Լ���� 15 �����о������������ Discord Radar ժҪ֪ͨ��ֻ������ 15m/1H K���� Radar D1 �о�״̬���ϸ���Ϲ��ڡ�δ�պϡ��쳣����Դ��һ�£��������κν����Ž���ʵ�� GitHub ���Ⱦ����� Discord �������Դ��ƶ����ա�

- [�Ľ�] Vibe-Trading historical capture preserves the Yahoo Chart raw payload hash and audits timezone/DST, XNYS calendar, source manifest, bar closure, and provider finality separately; missing evidence continues to block historical replay eligibility.
- [�Ľ�] Vibe-Trading Replay Lab V0.6 �� CSV ������ư󶨵� Replay ���沢֧�� JSON/Markdown �����fixture �����Ϊ `FIXTURE_SMOKE`��δ��֤֤�ݼ��������ʷ�ط��ʸ��� OOS ������
- [�Ľ�] Vibe-Trading Replay Lab V0.5 �������� OHLCV ����ѪԵ��ʱ�����������closure��provider finality�����ʶ��� replay eligibility �� fail-closed ��Ʊ��棻UNKNOWN ������Ϊ PASS��
- [�Ľ�] TickFlow ���� Premium ̽������ʽ��׼ģʽ�¶��� 15m/60m ��Ʊ��������ȡ��ȣ�ֻ�����н����������ö�٣�����-only ·����ȫ�� Radar/�����Ž����䡣
- [�¹���] Vibe-Trading Replay Lab ֧����ʽ�������б��� OHLC CSV����¼��Դ��ϣ������������ɱ������ԣ����ı��о���Radar �����Ž���
- [�Ľ�] Vibe-Trading Replay Lab V0.4 Ϊÿ������/���/�ɱ��������Ȩ�����ߡ����״������������ bar-low/close ���س��������ӹ�ϣ�󶨵��ϸ� Walk-Forward �����Ž���������������� OOS claim��

- [�޸�] �����ڷ�������ʷ���������ݷ�֧�������÷���δ�պϱ�ǣ�����ʷ�������ȷ����澯��TickFlow �о�״̬������ʷ��Ȳ�����գ���ֹ 4 �� 1H / 16 �� 15m �����Ϊ�ǲ��� K �ߡ�

- [�¹���] CN Radar ����ʽѡ������ TickFlow ���棬����ͬһ�������������ֻ���߱�ĵ� D1/60m/15m ��ʷ�о�״̬�������˶���Դ�汾��ʱЧ������δ�պϼ��Ž���ϣ���������Ӧ�̵��á�

- [�޸�] ���� Radar �������հ� systemctl ��ʱ����ʾ��ʽ�˶� 90 �� watchdog���������� shell ·���ع���ԣ��ܾ��رա�����ʱ�����޵�λԭʼ���֣��������ݺͽ����Ž��رա�
- [�޸�] A��ֻ�� Radar �������� owner/��ȷ main/��ʽ����У�顢��װ�����սű�˫��ϣ��飬��ֹ���� SSM ������빫����־������ Radar ��������о��¼���������Ž��ر�ʱʶ��δ�պ�Դ�ĺϷ���ϡ�
- [�޸�] OpenD �޶��ı��̽���ʹ�õ�ǰ���ӵĶ��ģ����������������״̬��������Ծܾ��������ж���ʱ�� K �ߵ��ò���ȷ��ϡ�
- [�޸�] TickFlow ������Ӧ©��ʱÿ���������ĸ�ȱʧ����ִ�е�Ʊ��ȡ��ÿ�������ڹ۲�����ʮ�Σ���ȡʧ�ܻ���ʱ������ϻ��档
- [�޸�] Vibe-Trading ��������������Ħ���ֶκ������� holdout ֤�ݴ���ʱͨ���ɱ�/OOS ��֤�������� B0/V0.2/Strong Pullback ��ֻ����Ȼ�����о���ڡ�
- [�¹���] Vibe-Trading �о����֧������ Replay Lab �����ԱȽϡ���ʽ�ɱ������ԡ����ɱ� fixture ��Դ��ϣ��������� holdout �Ҳ����� OOS ��֤���޳ֲֶ���·��ʱ���س���ȷΪ NOT_COMPUTED��С����ͳ����������ȷΪ���㣬�о�/�����Ž����ֹرա�
- [�Ľ�] TickFlow ˽���о����潫���� schema��provider ��״̬��ƥ��ֳɹ̶����������룬�����ƶ˶�λ������ fail-closed��
- [�޸�] ������ʷK�߷�ҳ�α�󶨲�ѯ��������ֹ�����ڷ�Χ���ú��������ݡ�
- [�¹���] ����ֻ�� `get_historical_bars` �����ȡ��Լ���޶� US �����ڡ�QFQ/RTH�����ڷ�Χ�����У����ԴԪ���ݡ�ʱ�����������պ�״̬��OHLCV ����հ󶨷�ҳ����ִ�� provider I/O��finality �� Radar/�����Ž����� UNKNOWN/BLOCKED��

- [�¹���] Ĭ�Ϲرյؽ�ͨ US Radar �־��¼����У������н� AI ����ѭ����ֹͣ��ϵ��ִ�ָ����Լ�������ʱ/��ѹ/δ֪״̬��ƣ������������������룬�����ø��ѵ��û��ƶ˷���
- [�޸�] OpenD �����װ��ȴ����� ACK ������ session ���ݡ��н�˳�򷢲����ܾ�/�쳣/����������������Σ���������ʷ��ʵʱԴ���� VWAP Խ����ϡ�
- [�޸�] TickFlow AUTO_200 �����������ڱ������� ETF �۲켯��������Ծ��Ʊ�������ɼ�ʧ�ܱ����̶��׶���ԭ��ö�٣���Ƹ���ȫ�������ڼ� 200 ��ı߽硣

- [�¹���] ����Ĭ�Ϲرյ� Radar �������о�ģ�ͺ�ˣ�SDK �����ԡ��̶��ӽ���Ӳ��ʱ�����������������ִ�����ó־û�Ԥ�㼰 UNKNOWN ���ط��Ž��������ø��ѵ��û��ƶ����С�

- [�¹���] �պ������˱�����Ĭ�Ϲرյ��о� AI ���ѻ�ִ������ǰ�־�ռλ������ȱ���� ACK������ȥ�ء��־õ������ޣ���ʱ��δ֪���������ԣ������ر��ź��뽻���Ž���
- [�޸�] OpenAI ������ Costs ���ø�����Ч��ÿ��Ͱ���ޣ����������˵����ڼ���ҳ��ϣ�Aider �� Token �������ʱ���ñ��δ֪����ض�����غɻع���� Windows��

- [�¹���] ���� canonical Radar ��ѯ������ʽ����־ñպ������˱����ϸ�У�� US OpenD ��������ʱ�Ρ��պ��������ʶȺͳɽ��д��ʧ�ܱ���Դ�������ԣ�����¼�о��۲죬Ĭ�Ϲرգ������� AI��֪ͨ���ס�
- [�¹���] ���Ӹ���ıպ�K�ߺ�ѡ�¼� SQLite �˱����� provider/symbol/timeframe/bar_end/rule revision/signal kind �ȶ�ȥ�أ�У��պϡ���������ȷ��ʱ�Ρ���ȷ���ʶȡ�����OHLCV����Դ���ݣ�����д������������Լ���������λ��ѣ�����������ͻ���������Ծ���ʽʧ�ܻ�������š��� seam ��δ���� Radar/AI/֪ͨ����ʱ���������ƶ����ջ�׼�롣
- [�Ľ�] ����ֻ�� Radar systemd worker ���� 90 �� systemd watchdog ������ notify ����Э�飬����ʱ�Զ��������ƶ����ռ����������� watchdog ���ã����׼� Radar ׼�뱣�ֹرա�
- [�޸�] �����ƶ��о��򱨽����г��� Radar ��Դ����һ�������һ������ʱ������������Ρ�ÿ��50�������ı��ؿ������¶�ȡ���Լ�־�ȷ����ƥ����������Ч�ԣ����������н����Ž��رա�
- [�޸�] Paper AWS SSM ֻ��������������ִ�гɹ�������ʱ��ʵ���飻ȱʧ����SHA���ر��Ž����������ʶ�֤��ʱ��������ȷʧ�ܣ��Բ�֤��ģ��ɽ��� L2 ׼�롣
- [�޸�] �ƶ� TickFlow Premium ����Ӿɵ������/������Ĭ�Ϸ�Χ��չΪ�ĸ��ֲ� ETF �� 1m/5m/15m/60m/1d �о�����MCP ������ȡ�� AWS ���ͬ�����ǣ��Ա��ֱպϡ���ǰ���� Radar/����׼��δ��֤��
- [�Ľ�] TickFlow ����ֻ��������ƶ� WebSocket/K��̽��ͳһ���ǳֲ��� ETF��159611��159209��512730��159363���� 1m/5m/15m/60m/1d �����о�ͨ���Բ��������ձպϡ�ʵʱ�����Ի� Radar/����׼�롣
- [�Ľ�] �ƶ�ÿ�շ����������� TickFlow Key ʱĬ�Ͻ� TickFlow ���� A �����ߡ�ʵʱ�����ָ������·����λ��ʧ�ܺ��԰����� fallback ������
- [�Ľ�] Ϊ CN TickFlow �о� worker ����Ĭ�ϹرյĹٷ� WebSocket quotes ֻ��֤�ݹ۲�㣬�����䰲ȫͶӰ�� Radar �о����棻���ı�ʵʱ�����ԡ�K �߱պϻ� Radar ׼�롣
- [�о�/����] TickFlow ����K������˫����ʱ�䵽����OHLCV�ȶ���ֻ��֤����ƣ��ϸ��빩Ӧ�����ձպϷ��룻δȡ��TickFlow����ȷ����Լǰ����������Radar�����Ž���
- [�޸�] Paper SSM ֻ�����վܾ�δ��ʱ����������ļ���Ϊ����״̬����������ʱδ֪�����н����Ž���ϡ�
- [�޸�] OpenD canonical �������ַ�����������������Դʱ���������ʱ�ɳ����ƽ�ֻ���������У�ͬʱ MCP �԰���ʵ K ��Դʱ���ж����ʶȣ����⻺��ͣ�ͻ�����ˢ���ڸǾ����ݡ�
- [�޸�] TickFlow ��ʱ�����糬ʱ��15��300���н��˱ָܻ����ɹ������ã���Ȩ�����������ݴ����Ա���300���˱ܣ���ĩ900�룬ʧ�ܻ��治ð����Ч���顣
- [�޸�] Context Manager ʹ�ÿ����д���������¼��汾��ͻ����ʽ�ָ���������У��������ظ��汾���ȱ���0600ԭʼ���ݣ����ı��κν����Ž���
- [�Ľ�] MCP ����ʧ�ܽ������̶�������࣬���ڶ�λ�¼���־�����ԡ����С�������Ȩ�����⣻ԭʼ SSM �Ͱ�װ����Բ�������ʧ�ܼ�����ϡ�
- [�޸�] OpenD ����ĩ�������߽�������390������ʷ���������޲��룬������ʷ��Դ�ͱպ�δ��֤״̬��ʧ�����30���Ӻ�����һ�Ρ�
- [�޸�] Paper �ֽ�Ԥ������ͼ���룬ģ��ɽ�������У�����ݡ��޼ۡ��ʽ𼰳ֲ��ټ��ˣ����������벿�ֳɽ��ع顣
- [�Ľ�] Paper ��Сʱ���������߱�48����������ʱ�Σ�����������״̬��ʵ�ʵ���ִ����������֤�ݡ�
- [����] TickFlow AWS�о�Worker������С��ѯ�������15�룻�ĳֲ�������ÿ�����20��K������ʧ����ǽ���ʱ���˱ܱ��ֲ��䣬�˺Ź�������Դ����顣
- [�޸�] OpenD �ۺ�K�߽���ȫ��Դ���ӳɽ����������Ƶ�VWAPλ�ڸ�K�߼۸�������ʱ����VWAP��Խ��򲿷ֳɽ��������������źš�
- [�Ľ�] TickFlow ��ʷ����������ӹ̶�ö����ϣ�AWS ��ƽ�����������ԭ�򣬲���¶����ֵ��ά�� fail-closed��
- [���] AWS TickFlow ��ETF 5m/15m/60m SSM+MCP ÿ����/���ֻ����ƣ�Windows ���ض�����Сʱƾ�ݰ�ȫȡ��������������״̬�������Ž���׼�롣
- [�޸�] �ƶ˵������� Discord/Telegram ��������Ӧ������ User-Agent��Telegram �ܾ������Ԥ���� HTTP ״̬�룬�����������ʧЧ��������ϡ�
- [�޸�] Discord ��· Webhook ������ HTTP 403 ʱ��ʹ�������� Telegram �û�����ƾ�ݷ���һ�ΰ�ȫ�������ѣ���·��ʧ���Է��غ�ƣ���������/�ƶ�Ȩ�ޡ�
- [�޸�] ����/����֪ͨ���������õı�׼ Discord Webhook ���λ��ˣ������ƶ˱�������������Ϣ�� HTTP ʧ��״̬�빩���ϡ�
- [�޸�] �ƶ˹�Ӧ�̷������ѷ���ʧ��ʱ�������ɢ������࣬��й¶ Webhook/API �������ģ�����֪ͨʧ��ʱ�� CI ��ơ�
- [�¹���] �ƶ� OpenAI API �ɱ�/token ʹ������ TickFlow �·ѵ��ڰ�ȫ���ѣ�ֻ�� Admin API��Discord��������ʵֵ��ȷ��ע����OpenD ��Ѳ���ء�
- [�о�����] TickFlow 5m ����΢С OHLC vendor float��<=1e-5��ETF tick-grid һ�£�������ԭֵ���������о���5m ȫ������K����һУ�飬ȱ�ںʹ�����Ծܾ��������Ž����䡣
- [�޸�] TickFlow����MCP��ȡ���������µ���ʱ������ڶ��ڸ�ͬ���м�ȱʧK�ߣ���ȡǰ����������޻��棬��ʹ limit=1 Ҳ�ܾ�δ��֤����ʷ��Ⱦ���Ա����о������뽻���Ž����롣
- [�Ľ�] ���� ChatGPT A�� MCP ��ȷ���� `TICKFLOW:PROGRESS:<ETF>` ֻ�����е��������о���ڣ�5m/15m/60m�����������������ӹ��ߣ��ϸ�����ʷ�о���Ĭ����Ѷ/�����Ƹ������������ձպϼ�����Ȩ�޸��롣
- [����] TickFlow�ƶ����� `TICKFLOW:FULL` һ��MCP���÷�����ETF��5m/15m/60m/D1��ʷ�о����ݣ�ͳһԴ�汾���룬�κ�����ʧЧ������ܾ����޽���Ȩ�޽�����
- [�Ľ�] TickFlow �ƶ˸����о����油������5m��48��/���������գ���1d����K�ߣ�������ETF�����������µ�Ȩ�ޡ�δ֪�պϡ����߽���ʷ�о���ԭ��15m/60m���ü��ݲ��䡣
- [����] ���� AWS OpenD ԭ���Ѷ��� K��������ٶȵ��н�ֻ�����գ���2000�������65�Σ������ϸ����� native��Radar���桢ChatGPT MCP �뱨�����ɺ�ʱ��
- [�޸�] ���� CN TickFlow �о������������ڶ����̶� Ubuntu EC2 ʵ���Ͼ� SSM �����ߡ��о����������С����������ɾ������� LiveFeed/MCP ���������Ķ�����֤����£����� Ubuntu ʵ��������׼�뼰Ĭ�� dry-run ������ϡ�
- [����] �ƶ� TickFlow ���� `TICKFLOW:FAST` ����������գ����������ӵ� `get_cn_market_data` һ�η��� 2 ETF��(15m,60m) ���һ��ԭ�� OHLCV��K�������뻺��ͬԴ�汾�������� AWS ���ض���ʱ����Ҫ������ MCP ��װ�����޸�ԭʼ���顢�����Ž����䡣
- [�޸�] TickFlow �����̺�15:02 �Ϻ�ʱ��󣩽���ԭʼ ETF �۸�ȫ��������С������OHLC ƫ����� 1e-5 ʱ����΢С����������ʷ�о� K �ߣ�����ԭʼ�ۡ���֤����̬�������� Session Progress ���ϸ���ϡ�
- [�Ľ�] �ƶ� ChatGPT ������ MCP �� `TICKFLOW:BATCH` ��ʽֻ��������һ�λ�ȡ��ֻ ETF �� 15m/60m ������ʷ�о� K �ߣ��ϸ�Ҫ�󻺴� SHA/sequence ͬԴ�����ı���ͨ����·�����������ձպϡ�Radar �����Ž���
- [�Ľ�] ChatGPT ���� `get_cn_market_data` ֻ������֧����ʽ `TICKFLOW:159611.SZ` / `TICKFLOW:518880.SH` ǰ׺����ȡ AWS ԭ�� TickFlow 15m/60m ��ʷ�о����棻��ͨ����·�������ձպϺ�ȫ�������Ž������䡣
- [�Ľ�] Ϊ CN Worker/TickFlow ������ʽĿ�ꡢĬ�� dry-run��SSM ����Ԥ�졢�ܿػع��Ͷ����汾/��Դ���صİ�ȫ�������

- [�޸�] �о� EOD ��ʱ�ɼ�Ҫ������ universe ����� A/US ������֤��ȱʧ��Ӧ�̷����� OHLCV ʱ���������� fail-closed���Ա���ʧ�� manifest �� artifact���������о��ɼ��� OpenD/����׼�롣

- [�޸�] TickFlow �ٷ����� 1e-5 OHLC ���㾫���ݲ�����о�������ֻ����������˫��У�飬����ԭʼ�۸��쳣��ǣ������Ծܾ���K ����̬������Դ/�״�/Paper/ʵ���Ž����䡣

- [�Ľ�] ����ֻ�� MCP/Context Manager �����������ܱ��� main ʱ�����òֿ� Owner��OIDC���̶� AWS Ŀ���뾫ȷ SHA У���Զ������ƶ�ֻ���������޹� PR ����������������ʧ�ܼ�����ϡ�

- [�Ľ�] ���� AWS exact-main �ƶ�ֻ������̽������ GitHub Owner ר�� PR ָ����ڣ����ڸ��˵��Թػ�ʱ�����۲���������/ʱ�����ʶȼ��պϣ����ƶ� SHA���� D1��MCP δ��֤���ϸ���������뽻�ס�

- [����] TickFlow ��ʷ OHLC Ӳ�ܾ������ٷ����� 1e-5 ���Ȳ��������ö����ƣ�����ӡ�۸��ԭʼ�쳣�����������ۡ�������κ�����Դ�뽻��׼�롣

- [�Ľ�] Paper AWS ֻ�� SIM �˻��������Ӿ� GitHub �ֿ� Owner �ϸ���Ȩ�Ĺ̶� PR ָ����ڣ����� latest main + OIDC + �̶� EC2 �ϲ�ѯģ���˻�������ȡ REAL �˻�������µ��������� Paper �� Radar��

- [�޸�] Context Manager �����зǳɹ� CI ���� fail-closed������ PR-head CI �� main ���գ��������Ѽ�¼�� PR �ϲ��벿�� SHA ��һ�¡�

- [�޸�] AWS OpenD/MCP ֻ�� SSM ʧ��ʱ�������ش��̶��׶�״̬�룬����ʧ���˳��룬����ԭʼ stdout��stderr���˻�����Կ��̽����ϲ������������׼�롣

- [��ά] ���ܱ��� main �� AWS SSM ֻ��·�ɸ��º��� GitHub �ƶ������ɷ�Ψһ�̶� `us_livefeed_status` ��������̽�룻��������ɷ������ѹ������ɹ���������պϻ���׼�룬�������û����Գ���������

- [�޸�] AWS US LiveFeed SSM ֻ��״̬̽���Ϊ�����н�����Ԫ���ݣ�������QOT_RIGHT��ʱ������ K ������������ʱ�䣩�����ٱ�����ԭʼ������־�� SSM stdout �ض��ڱΣ���Ϊ�о�״̬������������Դ���ס�

- [�Ľ�] Context Manager ������ CI��PR������Radar�������������������Ŀɻָ����գ���ͨ�� owner/OIDC/�̶� SSM/exact-main �����Զ����պϲ� PR �� main CI ����¼����ָ������ȷ���� provenance��TTL��δ���պ͹ر�״̬�����ı佻���Ž���
- [�޸�] AWS OpenD SSM ֻ��̽����־��������״̬ö�١��ϸ�ʱ������������ڰ�����������˽��·�����˵㡢������ֵ���ɽ����ݣ������ɹ�������ʵʱ����׼�롣

- [�¹���] �����ɳ��� Context Manager MVP�����̡�����CI �� Radar �¼���ͨ��ͳһ append-only JSONL ��¼����ǰ״̬ԭ�����̲����汾��ʱ�������Դ��TTL���ݵ���ƾ�ݹ��ˣ�����ֻ�� MCP ���� `get_context_manager_state` �ָ���ڣ�ʧЧ���𻵺�ʧ��״̬������ϣ����ı佻��Ȩ�ޡ�
- [�޸�] TickFlow�ƶ�ֻ����Ʋ������ӹ��������Ƶ���Ȩ���job������ֹ��Ȩ��GitHub�����滻���Ŷӵ�Owner��������
- [�޸�] Paper SIM ˽�лض������� JSON ����Ƕ����ȵĽṹ����Ϊ PRIVATE_SCHEMA_INVALID���﷨�����������Ϊ PRIVATE_INPUT_INVALID���ϸ�����������ײ��䡣

- [�Ľ�] GitHub�ֿ�Owner���ù̶�PR��ȷ���۴���TickFlow AWSֻ����ʷ/���������������飬������˵��ԣ�˫��Owner������main���飬�����Ž����ֹرա�

- [chore] Trigger protected AWS TickFlow read-only research re-audit after scoped main-branch audit changes without paid ingestion or trading changes.

- [�޸�] AWS ֻ�� MCP �ֶ����������ֿ� Owner ������ main SHA ˫�׶��������̶���װ�ű�У��͡���ֹԭʼԶ�˰�װ��־��й�����Զ��������������Ž���

- [�Ľ�] �ƶ� MCP ���� `get_market_analysis` �ӿ�֧�־�ȷֻ�� Cloud Ops ���ݲ������������� ChatGPT �ͻ��˹��ߣ��������ɷ��������н����Ž����ֲ��䣬���뾭 AWS ʵ�ʲ�������ա�

- [�Ľ�] �ڶ���� ChatGPT STOCK RAZOR �����嵥��ͨ��ԭ�� `get_cn_market_analysis(symbols=["__QUICK_SCAN__"])` �����Ѳ���� CN ���ν����о��챨���������Ӧ�ù���Ŀ¼����ͨ���ŵ��ñ��־����塢���н����Ž����䡣
- [test] Independently cross-check historical Eastmoney and qualified Tencent Kline clock grids/price values on AWS without source promotion.

- [chore] Run the existing cloud-only TickFlow research acceptance audit on weekday Shanghai market sessions; keep all source, Radar and trading gates closed.

- [�޸�] ���� CN Quick Scan AWS SSM ���ʹ�� dash ��֧�ֵ� `set -o pipefail` ���·����� 2����Ϊ POSIX `set -eu`�������ӻع���Լ��顣

- [����] AWS SSM Ops �����н�ֻ�� CN Quick Scan �ƶ�������ڣ��˶�ʵ�ʲ��� SHA��MCP ����ע�ᡢ�о���������˻����ȡ��ʱ�����������ң�⣬���������뽻�װ�ȫ�Ž����䡣
- [�Ľ�] AWS ֻ��������������е� MCP ����״̬��Git SHA �� Cloud Ops ����Դ��������飻��ȷЭ��ɵ�������δ���գ�������ƾ�ݡ���ִ��ά�����

- [�޸�] AWS ֻ��������Ƽ� Cloud Ops ������鰴���������ȡ���ʱ���жϣ������Ƶ US Radar �������ʱ�ӻز���ʵ��ʱ��ز�����ϡ�

- [�Ľ�] GitHub �ֿ� Owner ��ͨ���̶� PR �ľ�ȷ���������ԭ�� AWS ֻ�� SSM ��ƣ�ִ��ǰ˫�����ݼ���� main SHA У�飬��ֹ�������ʵ�̼����Ȩ�ޣ���������ʱ����� IAM Ȩ�ޡ�

- [�޸�] AWS ֻ���ƶ�������������� OIDC Ȩ��ǰ������ SSM ����ǰ����У�� main ��ǰ SHA���ܾ��������񣬲���ȡ��Կ�����ķ�������Ž���

- [�¹���] ����ֻ�� MCP �����̶����� AWS EC2 ���� systemd/���������鿴��ڣ�ʹ���ϸ�ȫ�ֶΰ���������ִ�� AWS API��SSM ��������������ף�ChatGPT Զ�̹���Ȩ���Դ�������Ȩ��

- [chore] ͳһ STOCK RAZOR ���湤�̵����˹�����ִ�й��򣺰���������֧������Զ��� CI �Ž�ͨ�����ƽ� PR �ϲ���ȡ��������û���׼��Code Owner ǩ�֡��˹� reviewer/ACK ����ʽ�������������������뽻�װ�ȫ׼�������ϡ�

- [�Ľ�] ѡ�ɽӿ����� `cache_only` �о�ģʽ��ֻ��ȡ���п��ջ��棬����ȱʧ�򳬹���Ч��ʱ fail-closed���������ⲿ����Դ�������ȷ���Ϊ research-only����Ҫʵʱ��ѡȷ���Ҳ���ֱ��ȷ���źš����ݿ�/CNEquity �������·����

- [�¹���] ����ֻ�����п���̨ `/operations` �� `GET /api/v1/operations/status`������չʾ Radar/Source Arbiter��֪ͨ������Paper Auto �� LIVE_TRADE �Ž����ӿڲ��ܽ�����ʵ���ף��ֻ����ա�TickFlow ʵ�������Ժ� Paper ���������Ա��ִ����ա�

- [�Ľ�] AWS TickFlow ����̽������ `premium-contract` fail-closed ��Լ��飻�����ƾ�����á�IAM����Ӧ����Ȩ������/������WebSocket����Ⱥ������ʸ��Ž�������ȡ secrets�������� Premium ���󣬲����� Radar/������ϡ�

- [�޸�] AWS Source Arbiter Shadow ��������Ѵ��ڵ� READ_SURFACE_NOT_FRESH_UNQUALIFIED ��ϱ�ǩ����ֹ US Radar expected-source ���°󶨺����� fail-closed ״̬��Ϊ�ƶ�ִ��ʧ�ܡ�

- [���] US AWS Shadow ֻ���ȶ� LiveFeed��Canonical��Radar expected-source �� commit/runtime ���ݣ���������Դ��һ���� Radar �ɰ汾 pin�����������ֵ����������׼����ϡ�

- [�޸�] Cloud Fast Path �����ظ���ȡ���ٽ�ͬһ�� Provider/Radar ��ʷ��ʱαװΪ 30 �ζ����¼��� P50/P95/P99��ͬʱ���� Futu ʵ���г�ʱ��ʶ����һ���Ի���ң���ע��

- [�Ľ�] AWS US Cloud Shadow ֻ��˫�������� Canonical?Radar ��������֤�ݡ�runtime identity ���������ظ���ѯʶ�𣬱��� Radar increment��Source Qualification ������Ȩ��δ��֤/��ϡ�

- [�޸�] AWS US Cloud OpenD Shadow ��Ƹ�����ʵ Futu ����ʱ��ö�٣����ַ���������Canonical ����״̬����ڻ��棻��ϱ��� UNKNOWN/BLOCKED��ֻ�����㽻��Ȩ�ޡ�

- [�޸�] US OpenD persistent livefeed ͨ������ RuntimeBridge ��¼ controller �����¼����޸� heartbeat �� event_count �� last_push_utc ���������⣻���� UNKNOWN/BLOCKED/NO �����߽硣
- [�޸�] Eastmoney ֻ���������Ľ�����ʱ���ѯ�����н� history_n������� StartTime ���� Daily ���ݲ�ѯʧ�ܡ�

- [�޸�] ���� RS Breakout ��֤����Ϊ��һ�����տ���ִ�о����������źţ�����ʹ��ͬһ�� K �����̼����ִ��ʱ��߹���

- [�Ľ�] ���� RS Breakout ��֤��֧�� `--round-trip-cost-bps` �ɱ�ѹ�����ԣ�ͬʱ��� gross/net ������ʤ��ָ�꣬���� guard �м�¼�ɱ����衣

- [����] Research Universe Capture ���������� 100/150/200 bps �����ɱ�ѹ�����������ɶ��� JSON ֤���ļ������ı�Ĭ�� Research-only �� Holdout �����߽硣

- [�޸�] RS Breakout ��֤���� capture �ڻ�� symbol ���޿�ִ�й۲촰��ִ�� fail-closed���������ɿ�����Ŀս����

- [�޸�] capture �����һ��У������ OHLC ���ι�ϵ��ǿ� symbol���쳣�����ڽ���ز�ǰֱ�Ӿܾ���

- [����] ÿ�� Research Universe Capture ���� +1 bar / +2 bar ִ���ӳ�ѹ���������� 100/150/200 bps �ɱ���������������֤�ݡ�

- [�¹���] �������� RS Breakout �о��ز���ڣ�ֻ�������Ѽ�¼ capture��У�� manifest hash/PIT �߽磬������෴��ʵ�� development/validation/Never-Seen Holdout �ֶ�֤�ݣ����������� routing�������� Holdout��

- [����] Radar Rule Validation Harness ��� Day 3�C7 �ϳ� fixture ���̱ջ������� ResearchDatasetCapsule��source/adapter/event hash/causal timestamps����ƥ�� reservation ���ܽ������ OOS Ledger������ counterfactual �ƻ�ȷ����ִ�У��������� RS-breakout �ϳ� fixture �� OOS BURNED �Ķ˵��˲��ԣ���ȷ�޻��� EOD OHLCV CSV ʱֻ����Ϊ synthetic-fixture validation����ʵ���� OOS �� Promotion ����ϡ�
- [�¹���] Radar Rule Validation Harness V0.1 ���ӳ־û� Experiment Registry ��ԭ��Ԥ�� reservation���� rule family �����׼� budget policy��SQLite `BEGIN IMMEDIATE` ���ض���������ִ�� PIT/contract preflight����鲢д�벻�ɱ� reservation��operation_id �ϸ��ݵȡ�experiment_id �����ظ�ע�ᡢ��Ԥ��� preflight ʧ����־û������ã��Ҹ� Registry ����ȡ���޸� Never-Seen Holdout��OOS Consumption Ledger ������ΨһȨ����
- [�¹���] Radar Rule Validation Harness V0.1 �����о�ר�ú�ͬ�� fail-closed preflight���ѹ������ݷָPIT policy��ʵ��Ԥ������� counterfactual �ƻ�����Ϊ�ɰ� `ExperimentManifest` ��ȷ����ָ�ƣ�PIT `UNKNOWN`/������ȱʧ/��ͻ�󶨻���һԤ��ά�ȳ��޾���� Never-Seen Holdout claim �ʸ񣻴� preflight ����������ֻ�� snapshot��ִ�м�ԭ�� reservation �ɳ־û� Registry �ṩ��
- [�¹���] ��Ŀ��ʽ����Ϊ Stock Razor�����Լ��ݷ�ʽ���� Radar��Realtime Monitor��Shared��Strategy Lab �� Infra ����߽磻��������֤�� Moomoo MCP ���̺�ѡ���˻�������״̬���ɱ��ػ���������
- [�¹���] Strategy Lab V0.1 ���� Parameter Drift������ʽ������Ϊ **Parameter Selection Identity Drift**���ļ�/ģ�������� `parameter_drift.py`���������� fold ��**��ѡ������������**�仯�������Ѳ�͸�� `selected_parameter_hash` ֤�ݡ����ⲻ�����������롢��ֵ delta������per-field Ư�ơ���������һ���ƶ������ֿⲻ���ڲ��� payload/schema/search-space ��Լ���κ���ֵ���붼��α���ȡ����� API `evaluate_parameter_drift(walk_forward_report, fold_parameter_selection_evidence=(), fixed_parameter_evidence=None)`��`WalkForwardValidationReport` ������ hash����֤�ݱ��뵥����Ӧ����ģ��**��ʵ����**�޷�֤����֤�ݾ���ԭ `validate_walk_forward` �������ã����� fold_id �� / �ʸ� / canonical ��󶨣�swap ���ɼ�⣩���ṹ���ã��������ظ� fold_id��֤���ظ�/δ֪ fold_id��ģʽ������֤�ݣ�һ�� `ValueError`���������� resolution��ģʽ��Լ��`FIXED` �� `NOT_APPLICABLE`��ȫ�� drift ָ�� `None`��observations/transitions Ϊ�ա�����¶ `fixed_parameter_hash` �������ġ�������α�� `unique=1/transition=0` ����Ư�Ʋ�����`TRAIN_ONLY`/`TRAIN_VALIDATION` ����ͬһ������Ư���߼��������� fixed evidence�������� gap ���壺�� `VALID` fold �������ݣ��� VALID fold ���������Ե�����ÿ�� transition �� `skipped_non_valid_fold_count`��VALID ȱ֤��**���**�����ԣ������ɿ� gap transition��stable-run ���ã����������ָ�꣺`transition_opportunity_count`/`transition_count`���� int����`transition_rate`��opportunity=0 ʱΪ None�������� 0.0����`unique_parameter_hash_count`���� segment����`longest_observed_stable_run`��0 observed=None�����۲�=1����**��** revisit_count/drift_score/severity label/��һ�� unique��Resolution ���ȼ����᣺FIXED �� NOT_APPLICABLE��any VALID missing �� INCOMPLETE_EVIDENCE��observed<2 �� INSUFFICIENT_DATA������ RESOLVED��missing ���� insufficient����������ȱ�������ڹ۲ⲻ�㣩���ĸ� finding �루`FIXED_MODE_NOT_APPLICABLE` ���漶��`VALID_FOLD_SELECTION_EVIDENCE_MISSING`/`NON_VALID_SELECTION_EVIDENCE_IGNORED` per-fold��`INSUFFICIENT_OBSERVED_SELECTIONS` ���漶���� `(code.value, fold_id or "", message)` ȷ���������� severity��������Ҷ�ӽڵ㣺�� stdlib + ��� Walk-Forward ���ͣ��� storage/repositories/SQLAlchemy/OOS ledger���� `parameter_stability.py` �㷨�����������ȶ���=��������³���ԣ�����һ���£��������� canonical ���� `(oos.start, train.start, fold_id)`��֤�ݰ� fold_id ӳ������ canonical fold�����������޹ء����öԿ����� 34 ��� FIXED ȫ None���ṹ���á�shuffle �����ԡ���ĸ��������gap/continuity ����̬��ָ��ȷ���ԡ�finding ������ score/label/revisit �ֶΡ��� persistence import��AST ���������α߽��ĵ����� swap-���ɼ����Ϊ��ס��
- [�޸�] OOS Consumption Ledger �۽��޸��ڶ��֣�5 ��������޶�����(1) **����ͼУ�������κ�д��**�����κ� Ledger д������ mutate ǰ���빹��"�ѳ־û�����ע��� + target-reachable ��ѡ����"����̬����ͼ��������֤���������� self-parent����ϵ�������������ƻ��� child/root ��ƥ�䣻��֪�ṹì��ֱ������ܾ����ع����� identity���� event����Ԥ�� operation_id������������ INDETERMINATE �� burn ������ֲ��������ϳ����û���INDETERMINATE burn ������"ȱʧ����"����Ч���ضϵ� target��ancestor ��������������֪ì�ܡ�(2) **д���ȼ�����**��idempotency ��λ�����þ����� ȫ�� supplied manifest ���Գ־û�ע����� identity ��ͻ��飨Ӳ `OOSLedgerIdentityConflictError`�������� self-parent/cycle/resolver �ض�/�ݵ��ط��ڸǣ��� ����ͼ�ṹУ�� �� �Ųþ��ݵ��ط�/��ͻ �� lineage ��� �� claim �ʸ�/��¶�߼���(3) **�ݵ��طű���ͨ������У��**����`IDEMPOTENT_REPLAY` ������վ����ͨ�� identity + �ṹУ���������ָ�ƾ�ȷƥ��ʱ���أ��ṹ�Ƿ��ı���طŰ� identity/lineage �����Դ���ʧ�ܣ��������� replay��ָ������У���ԺϷ� reachable �������ɡ�(4) **Ǩ���ϸ�У��**����`_ensure_oos_consumption_ledger_schema()` ����ȷ������ԼУ����ʵ SQLite Ԫ���ݣ������� + ���� NOT NULL��identity `id` INTEGER ������events `event_id INTEGER PRIMARY KEY AUTOINCREMENT`������ʵ DDL����`experiment_id`/`operation_id` ���������**ר�õ����ҷ� partial �� UNIQUE**������ UNIQUE �� `WHERE` ����Ψһ��������꣩��ʱ���� TEXT-affine����һ����� fail-closed ��**��**д�� `DatabaseSchemaMigration` �汾��¼��(5) **ȷ�����������ع����**�����������ӳ� `BEGIN IMMEDIATE`���� worker �ڽ��� Ledger дǰ�� started �¼��������ڼ������ done ��δ��λ���޾���ʱ���뼶��ɣ�δ��ɼ�֤����������ʵ SQLite д�������ͷź�ǡһ CLAIMED��һ ALREADY_EXPOSED��һ�¼�������ͼ�����Իع��׼���ͼ�ɵ�����չ�������ɻ����־û��ڵ㶨�岻�� mutation����ע�᲻�����뻷���޹ؽڵ㲻�ɶ���ͼ���κ�д���ð���ǰ�Ϸ��ĳ־û�ͼ��Ϊ��֪�Ƿ���ȫ�̲������崰���ص����塢�뿪���ڡ�BEGIN IMMEDIATE �ܹ���append-only �¼�Դ���־û�ͼ��ѯģ�͡�canonical UTC TEXT��aware �߽硢PRISTINE��BURNED ֱ�����ظ� claim �ܾ������ܲ�����Ԥ�� operation_id ���� reset API��
- [�޸�] OOS Consumption Ledger �۽��޸���һ�֣�9 ��������޶�����(1) **�� target-reachable ��ϵ�ڵ�**�ɱ�ע��/ָ�ƻ�/���ڼ̳С����� target �� `parent_experiment_id` �� root ׷�٣�ͬһ·����� co-supplied �ڵ㱻��ȫ���ԣ�������������ע������������� `lineage_binding_fingerprint`������Ӱ��������reachable �������� self-parent/cycle/��ͻ�ظ�����/���������ƻ�ʱ��Ϊ��ϵΥ�沢�ܾ�д�롣(2) **���� claim ��־û�������**����`LINEAGE_INDETERMINATE`/`LINEAGE_VIOLATION`/`ALREADY_EXPOSED` ������ event�������� identity �С������� operation_id��PASS claim ��ע�����¼���ԭ�ӣ���ע��� overlap �� ALREADY_EXPOSED����������ع�����ʱ identity ����������(3) **claim �Ž����ȼ�**���᣺identity ��ͻ=Ӳ�����Դ���lineage VIOLATION��`LINEAGE_VIOLATION`��INDETERMINATE��`LINEAGE_INDETERMINATE` �����ڱ�¶������ֻ�� PASS + �־û�ͼ RESOLVED �Ž��� PRISTINE vs ALREADY_EXPOSED �ж�������������ϵ + �������� OUTCOME_USED Ҳֻ�� `INDETERMINATE + state=None`������α�� ALREADY_EXPOSED/PRISTINE��(4) **��ϵ�淶��**���� target-reachable ���ϡ���ȷ�ظ��۵����� experiment_id ����fingerprint ������˳��/��ȷ�ظ�/unrelated �ڵ㲻�䣻reachable ��ͻ�ظ����� �� �ܾ���Υ�棩��������Ĭȥ�ء�(5) **�� AUTOINCREMENT**���¼������ñ��� `sqlite_autoincrement=True`��SQLite DDL ������� `INTEGER PRIMARY KEY AUTOINCREMENT`������ sqlite_master DDL ���Բ��ԣ�identity ��ά����ͨ INTEGER PRIMARY KEY ���ɣ��� id ���е�Ȩ������ְ�𣩡�(6) **Ǩ�� fail-closed**��`_ensure_oos_consumption_ledger_schema()` �ֻ���ʵ�ʴ��ڵ� Ledger ���������С�`experiment_id`/`operation_id` DB �� UNIQUE��event_id ���� + AUTOINCREMENT��ʱ���� TEXT-affine��������/��ȱ��ֱ�� `RuntimeError` ��**��**д�� `DatabaseSchemaMigration` �汾��¼��ȷ��˳�����Ϊ Ledger У�����ڰ汾���£�������"Ԥ�û��α� �� ��ʼ��ʧ�� �� �汾δ����"���ԡ�(7) **���ܲ�����Ԥ�� operation_id**���ݵ�����ֻ�����ѳ־û���״̬����¼������� claim ����ʱ����ǰ Ledger ״̬�������������ܲ�����ͬ������������� operation-attempt ����(8) **��������ǿ��**�����̳߳� `BEGIN IMMEDIATE` д�� + ���� barrier ͬ���� worker �������������ϣ����Գ����ڼ� worker �Դ����ͷź�ǡ��һ�� CLAIMED��һ�� ALREADY_EXPOSED����һ���¼���(9) **�����־û�����ǿ��**��claim �ύ�� `DatabaseManager.reset_instance()` + ���´�ͬһ SQLite �ļ���`get_assessment` �Է��� CONSUMED��ȫ�̲������崰���ص����塢�뿪���ڡ�BEGIN IMMEDIATE �ܹ���append-only �¼�Դ���־û�ͼ��ѯģ�͡�canonical UTC TEXT��aware �߽硢PRISTINE��BURNED ֱ�����ظ� claim �ܾ����� reset API��
- [�¹���] Strategy Lab V0.1 ���� OOS Consumption Ledger����Strategy Lab ��һ���־û�ģ�飬�ɴ����� domain �㣨`src/services/strategy_lab/oos_consumption.py`���� SQLAlchemy/SQLite �־ò㣨`src/repositories/oos_consumption_ledger_repo.py`�������� ORM �� `oos_experiment_identity_records`/`oos_consumption_event_records` ������ `src/storage.py`����ɡ�����״̬Ϊ���ᵥ���� `PRISTINE < CONSUMED < BURNED`��PRISTINE �Ӳ��ﻯΪ current-state �С���"�޺ϸ�¶�¼�"�������� PRISTINE��`CLAIMED_FOR_EVALUATION` ������Ϊ CONSUMED��`OUTCOME_USED` ��Ϊ BURNED������ PRISTINE ֱ�� BURNED����֪��Ⱦ������ȱ�� claim ��־���ܾ���¼������ֹ�κν��������� API �� reset/delete/unconsume/unburn������״̬�� `OOSConsumptionResolution`��`RESOLVED`/`INDETERMINATE`/`CONFLICT`�����룺��ϵ������ֻ�� `INDETERMINATE + state=None`������α�� PRISTINE���ٷ� claim �ʸ������� requested OOS ����Ϊ��λ���뿪�������ڲ��ص�������һ�ص� BURNED ��¶ �� ���� BURNED��������һ�ص� CONSUMED �� ���� CONSUMED������ PRISTINE���� per-segment claim eligibility��δ�� per-segment ���ֻ���Ƿ�Ȩ����ͼ������ window-padding/subset/superset/sliding-window/resegmentation ϴ�ס��ظ� claim �ѱ�¶���䷵�� `ALREADY_EXPOSED` �����Զ� burn��claim-before-evaluate ǿ�ƣ����ύ�� claim ��������������Ȼ CONSUMED��Ledger ���е��� `audit_experiment_lineage` ���̶� `history_complete=False`���������� caller �Ա� verdict��PASS+PRISTINE ������ claim��INDETERMINATE �ܾ� claim��abstain����VIOLATION �ܾ� claim �� burn���� `mark_outcome_used` �� INDETERMINATE ���� target ���ݱ�����������������¼��ʵ��Ⱦ����ȱʧ���Ⱦ���α�죬��ע������ȿ�ʹ�ѳ־û�ͼ INDETERMINATE��PASS���κ� mutation �����ý��������ɱ� first-seen ����ע�����`experiment_id` DB �� UNIQUE����ÿ�� experiment_id ���ð󶨵�Ψһ `manifest_hash`/`parent`/`root`��ì�ܼ� `OOSLedgerIdentityConflictError`������"�°汾"������ѯֻ���� `experiment_id` �����ӳ־û�ͼ�Ƶ� self+ancestors��caller �޷���ʡ�������ü��б�¶��ʧ������д������ `DatabaseManager._run_write_transaction`��SQLite `BEGIN IMMEDIATE` + �����ԣ���operation �ݵȲþ���identity register-or-verify��lineage ��ơ�overlap ����� event ����ͬһԭ���ٽ����������������ص� claim ֻ��һ�� `CLAIMED`��һ�� `ALREADY_EXPOSED`������ CLAIMED+CLAIMED��`operation_id` ȫ�� UNIQUE �Ұ�����ָ�ƣ�schema tag��event kind��experiment ���ݡ����䡢declared ʱ�䡢lineage-binding ժҪ�������ⲻ�� operation_id ��������ͬ id ָͬ�� �� `IDEMPOTENT_REPLAY`��ͬ id ��ָ�� �� `OOSLedgerIdempotencyConflictError`��`event_id` INTEGER AUTOINCREMENT Ϊ�־û�Ȩ������`recorded_at` ����ϣ�`declared_occurred_at` Ϊ caller claim �Ҳ�Ҫ�� `recorded_at >= declared_occurred_at`��Ledger �ǲֿ�־û�Լ���Ŀ������⣺����ʱ���д� canonical UTC TEXT�������òֿ� UTC-naive DateTime ����������ȡһ�ɻָ� aware UTC datetime��schema Ǩ�����ü��� `create_all` + `_ensure_oos_consumption_ledger_schema()` + `DatabaseSchemaMigration` ��¼���ƣ�`CURRENT_SCHEMA_VERSION` ����Ϊ `2026-09-07-oos-consumption-ledger-v0.1`���������� Alembic�����öԿ����Ը��ǣ��������� reset �����桢claim-before-evaluate��claim �ύ������� CONSUMED��ʧ�� claim ���׻ع����� PRISTINE���ݵ��ط������غɳ�ͻ��identity ���ֶγ�ͻ������ CONSUMED/BURNED �̳С���ѯ����ʡ�����ȡ�INDETERMINATE/VIOLATION �� claim�������ص�/�Ӽ�/����/padding �������á����ڰ뿪���������PRISTINE ֱ�� BURNED���ظ� claim �ܾ��� burn��**��ʵ��ʱ SQLite �ļ�**�ϵĲ����ص� claim ��ʤ��identity ע��+claim ԭ�ӻع���UTC TEXT ����� aware �������¼�д���޹ء�INDETERMINATE burn ��α�����ȡ���ע�����Ƚ������걸ͼ��ע������� mutation ������
- [�޸�] Walk-Forward Core Foundation �۽��޸���һ�֣�(1) warmup �� grid У�����������ֿɹ��쳡������feature set Ϊ `DECLARED` ʱ�ȶ� `evaluation_bar_grid_id`��feature set Ϊ `NOT_APPLICABLE` ������ warmup ��ȫ�� `DECLARED` `COLD_START` state �ṩʱ��Ϊ�ȶ� `state.payload.bar_grid_id`�����ֶ��� convergence_warmup_bars Ϊ��ʱ�����Ǳպ� `StateDependency` ��Լ�ı�����������죩����ǰֻ�� feature set Ϊ `DECLARED` ʱ���� grid �ȶԣ�state-only warmup �����ᱻ��Ĭ���С�(2) �����ǰ��ֱ�� `raise ValueError` ��ֹУ��ĳ����ָ�Ϊ����� finding �����������������桢������ֹ����`manifest.experiment_id` �� `lineage_audit.experiment_id` ��һ�¼�Ϊ���� `EXPERIMENT_IDENTITY_MISMATCH`��`FIXED` ģʽȱ�� `parameter_origin`/`fixed_parameter_evidence` �ֱ��Ϊ���� `PARAMETER_ORIGIN_REQUIRED`/`FIXED_EVIDENCE_REQUIRED`��`FIXED` ģʽЯ���ǿ� `fold_parameter_selection_evidence` ��Ϊ���� `FORBIDDEN_FOLD_SELECTION_EVIDENCE_UNDER_FIXED`�����߾�Ϊ `INVALID` ���� `fold_id=None` д�� `report_findings` ��ͬʱ���ָ��Ƶ�ÿ�� fold ������ findings�������ʵ�鼶 finding �㲥����һ�£���`ValueError` ��ֻ���������������ʹ��󡢸�����bool ð�� int��naive datetime �벻���ܵ� dataclass ���������������Լ����ı�̴���(3) `FIXED` ģʽ�� fold ����Ϊ��ʱ��parameter hash һ������ `PRIOR_EXPERIMENT` �����ü����Ȼ�ճ�ִ�У����߲������κ� fold ���ݣ��������� `min(fold.train_interval.start)` �� `information_horizon_end`/`declared_at` �߽���ᱻ���������Ǳ���һ�������ڵı߽磻`total_fold_count` ��Ϊ `0`��(4) �޸��� validation ���ѵ� fold ����֤����Я�� `applied_train_to_validation_purge_bars`/`usable_validation_bars` �� `None` ֵ�ᱻ��Ĭ���Ե�ȱ�ݡ��������߾���Ϊ `INVALID_FOLD_GEOMETRY`����Ϊ�� fold ���������� train-to-validation �߽�ɹ���Щ�ֶ�������(5) ͬһδ֪ fold_id ��ͬһ֤�ݼ����г��ֶ��ʱ����ֻ����һ�� `EVIDENCE_FOLD_ID_UNKNOWN`������ͬ id ȥ�أ�����ÿ��֤�ݸ�һ������������/���¸�������ȫ����Ϊ���������� fold ˳����֤��˳�򲻱��Իع������չ�� `report_findings`/`performance_eligible_fold_ids`/����������ԣ�����ֻ�Ƚ� `fold_results`��
- [�¹���] Strategy Lab V0.1 ���� Walk-Forward Core Foundation��`WalkForwardFold`/`FixedParameterEvidence`/`FoldParameterSelectionEvidence`/`FoldSeparationEvidence`/`FoldDataEvidence`/`UniverseIntegrityRequirement`/`FoldUniverseIntegrityEvidence`/`WalkForwardFinding`/`FoldValidationResult`/`WalkForwardValidationReport`����������ָ�ƺ��� `compute_window_configuration_fingerprint`/`compute_contamination_policy_fingerprint`/`compute_evaluation_protocol_fingerprint`���Լ���� `validate_walk_forward`����У����÷������� fold ���Ρ�����provenance���������֤�ݡ�information-dependency ����lineage ֤���� PIT universe ֤���Ƿ�ṹ��Ǣ�����Թ��� OOS ֤�ݣ��ش���ǡ����� walk-forward �����Ƿ��㹻�ṹ��Ǣ�Ա����Ρ��������ǡ���������Ƿ�ӯ�������������� performance/Sharpe/alpha�����Ż���������ӵ�г־û��� OOS Consumption Ledger�������� fold����ӵ�� trading calendar �� bar-grid ���㣬��ӵ�� universe checkpoint/�������ԡ��������Ѳ㣺���� import ��ʹ�� `experiment_go…54528 tokens truncated…eline conversion, and downstreamͳ��/֪ͨ����
- ?? **Multi-Agent partial-result fallback** �� `IntelAgent` now caches parsed intel for downstream reuse, shared JSON parsing tolerates lightly malformed model output, and the orchestrator preserves/synthesizes a minimal dashboard on timeout or mid-pipeline parse failure instead of always collapsing to `50/����/δ֪`
- ?? **Shared LiteLLM routing restored** �� bot NL intent parsing and `ResearchAgent` planning/synthesis now reuse the same LiteLLM adapter / Router / fallback / `api_base` injection path as the main Agent flow, so `LLM_CHANNELS` / `LITELLM_CONFIG` / OpenAI-compatible deployments behave consistently
- ?? **Bot chat session backward compatibility** �� `/chat` now keeps using the legacy `{platform}_{user_id}` session id when old history already exists, and `/history` can still list / view / clear those pre-migration sessions alongside the new `{platform}_{user_id}:chat` format
- ?? **EventMonitor unsupported rule rejection** �� config validation/runtime loading now reject or skip alert types the monitor cannot actually evaluate yet, so schedule mode no longer silently accepts permanent no-op rules
- ?? **P0 ������ۺ��ȶ����޸�** (#614) �� �޸� `get_stock_info` �������ع飨���� `belong_boards` ������ `boards` ���ݱ���������������������ľ��򷵻��Կ��� token��Ϊ�����滺�����������Ŀ��̭�������� ETF ����״̬�ۺ��� NaN ����ֶι��ˣ���֤ fail-open ����С���֡�
- ?? **GitHub Actions �������滷����������** �� ���������� `MINIMAX_API_KEYS`��`BRAVE_API_KEYS`��`SEARXNG_BASE_URLS` ��������ӳ�䣬ʹ GitHub Actions �û������� MiniMax��Brave��SearXNG �������񣨴�ǰ v3.5.0 ������ provider ʵ�ֵ�ȱ�ٹ��������ã�
- ?? **Multi-Agent runtime consistency** �� `AGENT_MAX_STEPS` now propagates to each orchestrated sub-agent; added cooperative `AGENT_ORCHESTRATOR_TIMEOUT_S` budget to stop overlong pipelines before they cascade further
- ?? **Multi-Agent feature wiring** �� `AGENT_RISK_OVERRIDE` now actively downgrades final dashboards on hard risk findings; `AGENT_MEMORY_ENABLED` now injects recent analysis memory + confidence calibration into specialised agents; multi-stock `/ask` now runs `PortfolioAgent` to add portfolio-level allocation and concentration guidance
- ?? **EventMonitor runtime wiring** �� schedule mode can now load alert rules from `AGENT_EVENT_ALERT_RULES_JSON`, poll them at `AGENT_EVENT_MONITOR_INTERVAL_MINUTES`, and send triggered alerts through the existing notification service
- ??? **Follow-up stability fixes** �� multi-stock `/ask` now falls back to usable text output when dashboard JSON parsing fails; EventMonitor skips semantically invalid rules instead of aborting schedule startup; background alert polling now runs independently of the main scheduled analysis loop
- ?? **Multi-Agent regression coverage** �� added orchestrator execution tests for `run()`, `chat()`, critical-stage failure, graceful degradation, and timeout handling
- ?? **PortfolioAgent cleanup** �� `post_process()` now reuses shared JSON parsing and removed stale unused imports
- ?? **Bot async dispatch** �� `CommandDispatcher` now exposes `dispatch_async()`; NL intent parsing and default command execution are offloaded from the event loop, DingTalk stream awaits async handlers directly, and Feishu stream processing is moved off the SDK callback thread
- ?? **Async webhook handler** �� new `handle_webhook_async()` function in `bot/handler.py` for use from async contexts (e.g. FastAPI); calls `dispatch_async()` directly without thread bridging
- ?? **Feishu stream ThreadPoolExecutor** �� replaced unbounded per-message `Thread` spawning with a capped `ThreadPoolExecutor(max_workers=8)` to prevent thread explosion under message bursts
- ?? **EventMonitor safety** �� `_check_volume()` now safely handles `get_daily_data` returning `None` (no tuple-unpacking crash); `on_trigger` callbacks support both sync and async callables via `asyncio.to_thread`/`await`
- ?? **ResearchAgent dedup** �� `_filtered_registry()` now delegates to `BaseAgent._filtered_registry()` instead of duplicating the filtering logic
- ?? **Bot trailing whitespace cleanup** �� removed W291/W293 whitespace issues across `bot/handler.py`, `bot/dispatcher.py`, `bot/commands/base.py`, `bot/platforms/feishu_stream.py`, `bot/platforms/dingtalk_stream.py`
- ?? **Dispatcher `_parse_intent_via_llm` safety** �� replaced fragile `'raw' in dir()` with `'raw' in locals()` for undefined-variable guard in `JSONDecodeError` handler
- ?? **����ṹ LLM δ��дʱ���ײ�ȫ** (#589) �� DeepSeek ��ģ��δ��ȷ��д `chip_structure` ʱ���Զ�������Դ�ѻ�ȡ�ĳ������ݲ�ȫ����֤��ģ��չʾһ�£���ͨ������ Agent ģʽ����Ч
- ?? **��ʷ����ѻ���λ��ʾԭʼ�ı�** (#452) �� ��ʷ����ҳ������չʾ `raw_result.dashboard.battle_plan.sniper_points` �е�ԭʼ�ַ��������� `analysis_history` ��ֵ�а����䡢˵�����ֻ��ӵ�λѹ���ɵ������֣�����ԭ����ֵ����Ϊ����
- ?? **Session prefix collision** �� user ID `123` could see sessions of user `1234` via `startswith`; fixed with colon delimiter in session_id format
- ?? **NL pre-filter false positives** �� `re.IGNORECASE` caused `[A-Z]{2,5}` to match common English words like "hello"; removed global flag, use inline `(?i:...)` only for English finance keywords
- ?? **Dotted ticker in strategy args** �� `_get_strategy_args()` didn't recognize `BRK.B` as a stock code, leaving it in strategy text; now accepts `TICKER.CLASS` format
- ?? **efinance �����ù����޸�** (#660) �� Ϊ���� efinance API �������� `_ef_call_with_timeout()` ��װ��Ĭ�� 30 �룬��ͨ�� `EFINANCE_CALL_TIMEOUT` ���ã���ʹ�� `executor.shutdown(wait=False)` ȷ����ʱ�����������̣߳��������� 81 ���ӹ�������
- ??? **���Ͱ�ȫ���������Լ��** (#660) �� `check_content_integrity()` ���ڽ����ַ������͵� `operation_advice` / `analysis_summary` ��Ϊȱʧ�ֶΣ��������� `get_emoji()` �� `dict.strip()` ����
- ?? **���汣����֪ͨ����** (#660) �� `_save_local_report()` �������� `send_notification` ��־������`--no-notify` ģʽ�±��ر����ճ�����
- ?? **operation_advice �ֵ��һ��** (#660) �� Pipeline �� BacktestEngine ���ڽ� LLM ���ص� `dict` ��ʽ `operation_advice` ͨ�� `decision_type`�������ִ�Сд��ӳ��Ϊ��׼�ַ�������ֹ��ģ�������ʽ�仯���±���
- ??? **runner.py usage None ����** (#660) �� `response.usage` Ϊ `None` ʱ�����׳� `AttributeError`������Ϊ 0 token ����
- ?? **orchestrator ��Ĭʧ�ܸ�Ϊ��־����** (#660) �� `IntelAgent` / `RiskAgent` �׶�ʧ�����ڼ�¼ `WARNING` ���Ǿ�Ĭ�������������

### Notes
- ?? **Multi-worker auth toggles** �� runtime auth updates are process-local; multi-worker deployments must restart/roll workers to keep auth state consistent

## [3.5.0] - 2026-03-12

### Added
- ?? **Web UI full report drawer** (Fixes #214) �� history page adds "Full Report" button to display the complete Markdown analysis report in a side drawer; new `GET /api/v1/history/{record_id}/markdown` endpoint
- ?? **LLM cost tracking** �� all LLM calls (analysis, agent, market review) recorded in `llm_usage` table; new `GET /api/v1/usage/summary?period=today|month|all` endpoint returns aggregated token usage by call type and model
- ?? **SearXNG search provider** (Fixes #550) �� quota-free self-hosted search fallback; priority: Bocha > Tavily > Brave > SerpAPI > MiniMax > SearXNG
- ?? **MiniMax web search provider** �� `MiniMaxSearchProvider` with circuit breaker (3 failures �� 300s cooldown) and dual time-filtering; configured via `MINIMAX_API_KEYS`
- ?? **Agent models discovery API** �� `GET /api/v1/agent/models` returns available model deployments (primary/fallback/source/api_base) for Web UI model selector
- ?? **Agent chat export & send** (#495) �� export conversation to .md file; send to configured notification channels; new `POST /api/v1/agent/chat/send`
- ?? **Agent background execution** (#495) �� analysis continues when switching pages; badge notification on completion; auto-cancel in-progress stream on session switch
- ?? **Report Engine P0** �� Pydantic schema validation for LLM JSON; Jinja2 templates (markdown/wechat/brief) with legacy fallback; content integrity checks with retry; brief mode (`REPORT_TYPE=brief`); history signal comparison
- ?? **Smart import** �� multi-source import from image/CSV/Excel/clipboard; Vision LLM extracts code+name+confidence; name��code resolver (local map + pinyin + AkShare); confidence-tiered confirmation
- ?? **GitHub Actions LiteLLM config** �� workflow supports `LITELLM_CONFIG`/`LITELLM_CONFIG_YAML` for flexible AI provider configuration
- ?? **Config engine refactor & system API** (#602) �� unified config registry, validation and API exposure
- ?? **LLM configuration guide** �� new `docs/LLM_CONFIG_GUIDE.md` covering 3-tier config, quick start, Vision/Agent/troubleshooting

### Fixed
- ?? **analyze_trend always reports No historical data** (#600) �� now fetches from DB/DataFetcher instead of broken `get_analysis_context`
- ?? **Chip structure fallback when LLM omits it** (#589) �� auto-fills from data source chip data for consistent display across models
- ?? **History sniper points show raw text** (#452) �� prioritizes original strings over compressed numeric values
- ?? **GitHub Actions ENABLE_CHIP_DISTRIBUTION configurable** (#617) �� no longer hardcoded, supports vars/secrets override
- ?? **`.env` save preserves comments and blank lines** �� Web settings no longer destroys `.env` formatting
- ?? **Agent model discovery fixes** �� legacy mode includes LiteLLM-native providers; source detection aligned with runtime; fallback deployments no longer expanded per-key
- ?? **Stooq US stock previous close semantics** �� no longer misuses open price as previous close
- ?? **Stock name prefetch regression** �� prioritizes local `STOCK_NAME_MAP` before remote queries
- ?? **AkShare limit-up/down calculation** (#555) �� fixed market analysis statistics
- ?? **AkShare Tencent source field index & ETF quote mapping** (#579)
- ?? **Pytdx stock name cache pagination** (#573) �� prevents cache overflow
- ?? **PushPlus oversized report chunking** (#489) �� auto-segments long content
- ?? **Agent chat cancel & switch** (#495) �� cancel no longer misreports as failure; fast switch no longer overwrites stream state
- ?? **MiniMax search status in `/status` command** (#587)
- ?? **config_registry duplicate BOCHA_API_KEYS** �� removed duplicate dict entry that silently overwrote config

### Changed
- ?? **Fetcher failure observability** �� logs record start/success/failure with elapsed time, failover transitions; Efinance/Akshare include upstream endpoint and classified failure categories
- ?? **Data source resilience & cleanup** (#602) �� fallback chain optimization
- ?? **Image extract API response extension** �� new `items` field (code/name/confidence); `codes` preserved for backward compatibility
- ?? **Import parse error messages** �� specific failure reasons for Excel/CSV; improved logging with file type and size

### Docs
- ?? LLM config guide refactored for clarity (#583)
- ?? `image-extract-prompt.md` with full prompt documentation
- ?? AkShare fallback cache TTL documentation
## [3.4.10] - 2026-03-07

### Fixed
- ?? **EfinanceFetcher ETF OHLCV data** (#541, #527) �� switch `_fetch_etf_data` from `ef.fund.get_quote_history` (NAV-only, no OHLCV, no `beg`/`end` params) to `ef.stock.get_quote_history`; ETFs now return proper open/high/low/close/volume/amount instead of zeros; remove obsolete NAV column mappings from `_normalize_data`
- ?? **tiktoken 0.12.0 `Unknown encoding cl100k_base`** (#537) �� pin `tiktoken>=0.8.0,<0.12.0` in requirements.txt to avoid plugin-registration regression introduced in 0.12.0
- ?? **Web UI API error classification** (#540) �� frontend no longer treats every HTTP 400 as the same "server/network" failure; now distinguishes Agent disabled / missing params / model-tool incompatibility / upstream LLM errors / local connection failures
- ?? **����������ʶ��ʧ��** (#491, #533) �� 8/4/92 ��ͷ�� 6 λ��������ȷʶ��Ϊ��������Tushare/Akshare/Yfinance ������Դ֧�� .BJ �� bj ǰ׺��Baostock/Pytdx �Ա�����������ʽ�л�����Դ�����������Ϻ� B �� 900xxx
- ?? **�ѻ���λ��������** (#488, #532) �� ��������/����������ֶ����ޡ�Ԫ����ʱ����ȡ�����ڼ���ָ�����֣����Ƚ�ȥ��һ�����ź���������ȡ

### Added
- **Markdown-to-image for dashboard report** (#455, #535) �� �����ձ�����֧�� markdown תͼƬ���ͣ�Telegram��WeChat��Custom��Email��������̸�����Ϊһ��
- **markdown-to-file engine** (#455) �� `MD2IMG_ENGINE=markdown-to-file` ��ѡ���� emoji ֧�ָ��ã��� `npm i -g markdown-to-file`
- **PREFETCH_REALTIME_QUOTES** (#455) �� ��Ϊ `false` �ɽ���ʵʱ����Ԥȡ������ efinance/akshare_em ȫ�г���ȡ
- **Stock name prefetch** (#455) �� ����ǰԤȡ��Ʊ���ƣ����ٱ����С���Ʊxxxxx��ռλ��
- ?? **��������ģ�ͱ��** (#528, #534) �� �ڷ������� meta������ĩβ������������չʾ `model_used`������ LLM ģ��������Agent ���ֵ���ʱ��¼��չʾÿ��ʵ��ʹ�õ�ģ�ͣ�֧�� fallback �л���

### Changed
- **Enhanced markdown-to-image failure warning** (#455) �� תͼʧ��ʱ��ʾ����������wkhtmltopdf �� m2f��
- **WeChat-only image routing optimization** (#455) �� ��������ҵ΢��ͼƬʱ�����ٶ���������������תͼ����������ʧ����־
- **Stock name prefetch lightweight mode** (#455) �� ����Ԥȡ�׶����� realtime quote ��ѯ�����ٶ������翪��

## [3.4.9] - 2026-03-06

### Added
- ?? **Structured config validation** �� `ConfigIssue` dataclass and `validate_structured()` with severity-aware logging; `CONFIG_VALIDATE_MODE=strict` aborts startup on errors
- ??? **Vision model config** �� `VISION_MODEL` and `VISION_PROVIDER_PRIORITY` for image stock extraction; provider fallback (Gemini �� Anthropic �� OpenAI �� DeepSeek) when primary fails
- ?? **CLI init wizard** �� `python -m dsa init` 3-step interactive bootstrap (model �� data source �� notification), 9 provider presets, incremental merge by default
- ?? **Multi-channel LLM support** with visual channel editor (#494)

### Changed
- ?? **Vision extraction** �� migrated from gemini-3 hardcode to `litellm.completion()` with configurable model and provider fallback; `OPENAI_VISION_MODEL` deprecated in favor of `VISION_MODEL`
- ?? **Market analyzer** �� uses `Analyzer.generate_text()` for LLM calls; fixes bypass and Anthropic `AttributeError` when using non-Router path
- ?? **Config validation refinements** �� test_env output format syncs with `validate_structured` (severity-aware ?/?/?/��); Vision key warning when `VISION_MODEL` set but no provider API key; market_analyzer test covers `generate_market_review` fallback when `generate_text` returns None
- ?? **Auto-tag workflow defaults to NO tag** �� only tags when commit message explicitly contains `#patch`, `#minor`, or `#major`
- ?? **Formatter and notification refactor** (#516)

### Fixed
- ?? **STOCK_LIST not refreshed on scheduled runs** �� `.env` or WebUI changes to `STOCK_LIST` now hot-reload before each scheduled analysis (#529)
- ?? **WebUI fails to load with MIME type error** �� SPA fallback route now resolves correct `Content-Type` for JS/CSS files (#520)
- ?? **AstrBot sender docstring misplaced** �� `import time` placed before docstring in `_send_astrbot`, causing it to become dead code
- ?? **Telegram Markdown link escaping** �� `_convert_to_telegram_markdown` escaped `[]()` characters, breaking all Markdown links in reports
- ?? **Duplicate `discord_bot_status` field** in Config dataclass �� second declaration silently shadowed the first
- ?? **Unused imports** �� removed `shutil`/`subprocess` from `main.py`
- ?? **Config validation and Vision key check** (#525)

### Docs
- ?? Clarified GitHub Actions non-trading-day manual run controls (`TRADING_DAY_CHECK_ENABLED` + `force_run`) for Issue #461 / PR #466

## [3.4.8] - 2026-03-02

### Fixed
- ?? **Desktop exe crashes on startup with `FileNotFoundError`** �� PyInstaller build was missing litellm's JSON data files (e.g. `model_prices_and_context_window_backup.json`). Added `--collect-data litellm` to both Windows and macOS build scripts so the files are correctly bundled in the executable.

### CI
- ?? Cache Electron binaries on macOS CI runners to prevent intermittent EOF download failures when fetching `electron-vX.Y.Z-darwin-*.zip` from GitHub CDN
- ?? Fix macOS DMG `hdiutil Resource busy` error during desktop packaging

### Docs
- ?? Clarify non-trading-day manual run controls for GitHub Actions (`TRADING_DAY_CHECK_ENABLED` + `force_run`) (#474)

## [3.4.7] - 2026-02-28

### Added
- ?? **CN/US Market Strategy Blueprint System** (#395) �� market review prompt injects region-specific strategy blueprints with position sizing and risk trigger recommendations

### Fixed
- ?? **`TRADING_DAY_CHECK_ENABLED` env var and `--force-run` for GitHub Actions** (#466)
- ?? **Agent pipeline preserved resolved stock names** (#464) �� placeholder names no longer leak into reports
- ?? **Code cleanup** (#462, Fixes #422)
- ?? **WebUI auto-build on startup** (#460)
- ?? **ARCH_ARGS unbound variable** (#458)
- ?? **Time zone inconsistency & right panel flash** (#439)

### Docs
- ?? Clarify potential ambiguities in code (#343)
- ?? ENABLE_EASTMONEY_PATCH guidance for Issue #453 (#456)

## [3.4.0] - 2026-02-27

### Added
- ?? **LiteLLM Direct Integration + Multi API Key Support** (#454, Fixes #421 #428)
  - Removed native SDKs (google-generativeai, google-genai, anthropic); unified through `litellm>=1.80.10`
  - New config: `LITELLM_MODEL`, `LITELLM_FALLBACK_MODELS`, `GEMINI_API_KEYS`, `ANTHROPIC_API_KEYS`, `OPENAI_API_KEYS`
  - Multi-key auto-builds LiteLLM Router (simple-shuffle) with 429 cooldown
  - **Breaking**: `.env` `GEMINI_MODEL` (no prefix) only for fallback; explicit config must include provider prefix

### Changed
- ?? **Notification Refactoring** (#435) �� extracted 10 sender classes into `src/notification_sender/`

### Fixed
- ?? LLM NoneType crash, history API 422, sniper points extraction
- ?? Auto-build frontend on WebUI startup �� `WEBUI_AUTO_BUILD` env var (default `true`)
- ?? Docker explicit project name (#448)
- ?? Bocha search SSL retry (#445, #446) �� transient errors retry up to 3 times
- ?? Gemini google-genai SDK migration (Fixes #440, #444)
- ?? Mobile home page scrolling (Fixes #419, #433)
- ?? History list scroll reset (#431)
- ?? Settings save button false positive (fixes #417, #430)

## [3.3.22] - 2026-02-26

### Added
- ?? **Chat History Persistence** (Fixes #400, #414) �� `/chat` page survives refresh, sidebar session list
- ?? Project VI Assets �� logo icon set, PSD, vector, banner (#425)
- ?? Desktop CI Auto-Release (#426) �� Windows + macOS parallel builds

### Fixed
- ?? Agent Reasoning 400 & LiteLLM Proxy (fixes #409, #427)
- ?? Discord chunked sending (#413) �� `DISCORD_MAX_WORDS` config
- ?? yfinance shared DataFrame (#412)
- ?? sniper_points parsing (#408)
- ?? Agent framework category missing (#406)
- ?? Date inconsistency & query id (fixes #322, #363)

## [3.3.12] - 2026-02-24

### Added
- ?? **Intraday Realtime Technical Indicators** (Issue #234, #397) �� MA calculated from realtime price, config: `ENABLE_REALTIME_TECHNICAL_INDICATORS`
- ?? **Agent Strategy Chat** (#367) �� full ReAct pipeline, 11 YAML strategies, SSE streaming, multi-turn chat
- ?? PushPlus Group Push �� `PUSHPLUS_TOPIC` (#402)
- ?? Trading Day Check (Issue #373, #375) �� `TRADING_DAY_CHECK_ENABLED`, `--force-run`

### Fixed
- ?? DeepSeek reasoning mode (Issue #379, #386)
- ?? Agent news intel persistence (Fixes #396, #405)
- ?? Bare except clauses replaced with `except Exception` (#398)
- ?? UUID fallback for HTTP non-secure context (fixes #377, #381)
- ?? Docker DNS resolution (Fixes #372, #374)
- ?? Agent session/strategy bugs �� multiple follow-up fixes for #367
- ?? yfinance parallel download data filtering

### Changed
- Market review strategy consistency �� unified cn/us template
- Agent test assertions updated (`6 -> 11`)


## [3.2.11] - 2026-02-23

### �޸���#patch��
- ?? **StockTrendAnalyzer ��δִ��** (Issue #357)
  - ����`get_analysis_context` ������ 2 ���������� `raw_data`��pipeline �� `raw_data in context` ʼ��Ϊ False
  - �޸���Step 3 ֱ�ӵ��� `get_data_range` ��ȡ 90 �����죨Լ 60 �����գ���ʷ�����������Ʒ���
  - ���ƣ����Ʒ���ʧ��ʱ�� `logger.warning(..., exc_info=True)` ��¼���� traceback

## [3.2.10] - 2026-02-22

### ����
- ?? ֧�� `RUN_IMMEDIATELY` �������Ϊ `true` ʱ��ʱ���񴥷�������ִ��һ�η���������ȴ��׸���ʱ��

### �޸�
- ?? �޸� Web UI ҳ���������
- ?? �޸� Settings ���� 500 ����

## [3.2.9] - 2026-02-22

### �޸�
- ?? **ETF ��������עָ������**��Issue #274��
  - ����/�۹� ETF���� VOO��QQQ���� A �� ETF �����������˾������գ����ϡ������ȣ�
  - ����ά�ȣ�ETF/ָ��ר�� risk_check��earnings��industry ��ѯ���������л������������
  - AI ��ʾ��ָ���ͱ�ķ���Լ����`risk_alerts` ���ó��ֻ�������˹�˾��Ӫ����

## [3.2.8] - 2026-02-21

### �޸�
- ?? **BOT �� WEB UI ��Ʊ�����Сдͳһ**��Issue #355��
  - BOT `/analyze` �� WEB UI ���������Ĺ�Ʊ����ͳһΪ��д���� `aapl` �� `AAPL`��
  - ���� `canonical_stock_code()`���� BOT��API��Config��CLI��task_queue ��ڴ��淶��
  - ��ʷ��¼������ȥ���߼�����ȷʶ��ͬһ��Ʊ����Сд����Ӱ�죩

## [3.2.7] - 2026-02-20

### ����
- ?? **Web ҳ��������֤**��Issue #320, #349��
  - ֧�� `ADMIN_AUTH_ENABLED=true` ���� Web ��¼����
  - �״η�������ҳ���ó�ʼ���룻֧�֡�ϵͳ���� > �޸����롹�� CLI `python -m src.auth reset_password` ����

## [3.2.6] - 2026-02-20
### ?? �ƻ��Ա����Breaking Changes��

- **��ʷ��¼ API ��� (Issue #322)**
  - ·�ɱ����`GET /api/v1/history/{query_id}` �� `GET /api/v1/history/{record_id}`
  - ���������`query_id` (�ַ���) �� `record_id` (����)
  - ���Žӿڱ����`GET /api/v1/history/{query_id}/news` �� `GET /api/v1/history/{record_id}/news`
  - ԭ��`query_id` ����������ʱ�����ظ����޷�Ψһ��ʶ������ʷ��¼���������ݿ����� `id` ȷ��Ψһ��
  - Ӱ�췶Χ��ʹ�þɰ���ʷ���� API �����пͻ�����ͬ������

### �޸�
- �޸����ɣ��� ADBE������ָ��ì�ܣ�akshare ���ɸ�Ȩ�����쳣��ͳһ������ʷ����ԴΪ YFinance��Issue #311��
- ?? **��ʷ��¼��ѯ����ʾ���� (Issue #322)**
  - �޸���ʷ��¼�б���ѯ�����ڲ�һ�����⣺ʹ��������Ϊ endDate��ȷ����������ȫ�������
  - �޸������� UI ����ѡ�����⣺ԭ���Ƕ�����¼����ͬһ `query_id`������������ʾ��һ�����ָ��� `analysis_history.id` ��ΪΨһ��ʶ
  - ��ʷ���顢���Žӿڼ�ǰ�������ȫ������ `record_id`
  - ������̨��ѯ��ÿ 30s����ҳ��ɼ��Ա��ʱ��Ĭˢ����ʷ�б���ȷ�� CLI ����ķ�����ɺ�ǰ���ܼ�ʱͬ����ʹ�� `silent` ģʽ���ⴥ�� loading ״̬
- ?? **����ָ��ʵʱ��������������** (Issue #273)
  - �޸� SPX��DJI��IXIC��NDX��VIX��RUT ������ָ���޷���ȡʵʱ���������
  - ���� `us_index_mapping` ģ�飬���û����루�� SPX��ӳ��Ϊ Yahoo Finance ���ţ��� ^GSPC��
  - ����ָ�������ɹ�Ʊ��������ֱ��·���� YfinanceFetcher�����������֧�ֵ�����Դ
  - �����ظ�������ʶ���߼���ͳһʹ�� `is_us_stock_code()` ����

### �Ż�
- ?? **��ҳ�������� Market Sentiment ���ֶ����Ż�**
  - ��Ʊ�����������Ե����ʷ��¼ glass-card �������
  - ������ť��Ե�� Market Sentiment ����Ҷ���
  - Market Sentiment ��Ƭ���������������ӣ������� STRATEGY POINTS ֮��Ŀ�϶
  - խ��ʱ�������������ȣ���Ӧʽ���뱣��һ��

## [3.2.5] - 2026-02-19

### ����
- ?? **���̸��̿�ѡ����**��Issue #299��
  - ֧�� `MARKET_REVIEW_REGION` ����������`cn`��A�ɣ���`us`�����ɣ���`both`�����ߣ�
  - us ģʽʹ�� SPX/��˹���/��ָ/VIX ��ָ����both ģʽ��ͬʱ���� A ��������
  - Ĭ�� `cn`������������

## [3.2.4] - 2026-02-18

### �޸�
- ?? **ͳһ��������ԴΪ YFinance**��Issue #311��
  - akshare ���ɸ�Ȩ�����쳣��ͳһ������ʷ����ԴΪ YFinance
  - �޸� ADBE �����ɹ�Ʊ����ָ��ì������

## [3.2.3] - 2026-02-18

### �޸�
- ?? **����500ʵʱ����ȱʧ**��Issue #273��
  - �޸� SPX��DJI��IXIC��NDX��VIX��RUT ������ָ���޷���ȡʵʱ���������
  - ���� `us_index_mapping` ģ�飬���û����루�� SPX��ӳ��Ϊ Yahoo Finance ���ţ��� `^GSPC`��
  - ����ָ�������ɹ�Ʊ��������ֱ��·���� YfinanceFetcher�����������֧�ֵ�����Դ

## [3.2.2] - 2026-02-16

### ����
- ?? **PE ָ��֧��**��Issue #296��
  - AI System Prompt ���� PE ��ֵ��ע
- ?? **����ʱЧ��ɸ��**��Issue #296��
  - `NEWS_MAX_AGE_DAYS`���������ʱЧ���죩��Ĭ�� 3������ʹ�ù�ʱ��Ϣ
- ?? **ǿ�����ƹɹ����ʷſ�**��Issue #296��
  - `BIAS_THRESHOLD`����������ֵ��%����Ĭ�� 5.0��������
  - ǿ�����ƹɣ���ͷ����������ǿ�� ��70���Զ��ſ������ʵ� 1.5 ��

## [3.2.1] - 2026-02-16

### ����
- ?? **���ƽӿڲ��������ÿ���**
  - ֧�� `EFINANCE_PATCH_ENABLED` �����������ض��ƽӿڲ�����Ĭ�� `true`��
  - ����������ʱ�ɽ����رգ�����Ӱ��������

## [3.2.0] - 2026-02-15

### ����
- ?? **CI �Ž�ͳһ��P0��**
  - ���� `scripts/ci_gate.sh` ��Ϊ����Ž���һ���
  - �� CI ��Ϊ `backend-gate`��`docker-build`��`web-gate` ����ʽ
  - CI ������Ϊ���� PR������ Required Checks ��·������ȱʧ����ס�ϲ�
  - `web-gate` ֧��ǰ��·��������败��
  - ���� `network-smoke` ���������ط�������糡���ع�
- ?? **������·������P0��**
  - `docker-publish` ����Ϊ tag �������������ӷ���ǰ�Ž�У��
  - �ֶ��������� `release_tag` ������ semver/changelog ǿУ��
  - ����ǰ���� Docker smoke���ؼ�ģ�鵼�룩
- ?? **PR ģ��������P0��**
  - ���ӱ�������Χ����֤�����������ع�������Issue �����ȱ�����
- ?? **AI ��鸲����ǿ��P0��**
  - `pr-review` ���� `.github/workflows/**` ��Χ
  - ���� `AI_REVIEW_STRICT` ���أ���ѡ�� AI ���ʧ������Ϊ���

## [3.1.13] - 2026-02-15

### ����
- ?? **���������ժҪ**��Issue #262��
  - ֧�� `REPORT_SUMMARY_ONLY` ������������Ϊ `true` ʱֻ���ͻ��ܣ�������������
  - Ĭ�� `false`�����ʱ�ʺϿ������

## [3.1.12] - 2026-02-15

### ����
- ?? **��������̸��̺ϲ�����**��Issue #190��
  - ֧�� `MERGE_EMAIL_NOTIFICATION` ������������Ϊ `true` ʱ�����ɷ�������̸��̺ϲ�Ϊһ������
  - Ĭ�� `false`�������ʼ����������ͱ�ʶ��Ϊ�����ʼ��ķ���

## [3.1.11] - 2026-02-15

### ����
- ?? **Anthropic Claude API ֧��**��Issue #257��
  - ֧�� `ANTHROPIC_API_KEY`��`ANTHROPIC_MODEL`��`ANTHROPIC_TEMPERATURE`��`ANTHROPIC_MAX_TOKENS`
  - AI �������ȼ���Gemini > Anthropic > OpenAI
- ?? **��ͼƬʶ���Ʊ����**��Issue #257��
  - �ϴ���ѡ�ɽ�ͼ��ͨ�� Vision LLM �Զ���ȡ��Ʊ����
  - API: `POST /api/v1/stocks/extract-from-image`��֧�� JPEG/PNG/WebP/GIF����� 5MB
  - ֧�� `OPENAI_VISION_MODEL` ��������ͼƬʶ��ģ��
- ?? **ͨ��������Դ�ֶ�����**��Issue #257��
  - ֧�� `PYTDX_HOST`��`PYTDX_PORT` �� `PYTDX_SERVERS` �����Խ�ͨ���ŷ�����

## [3.1.10] - 2026-02-15

### ����
- ?? **������������**��Issue #332��
  - ֧�� `RUN_IMMEDIATELY` ����������`true` ʱ��ʱ��������������ִ��һ��
- ?? �޸� Docker ��������

## [3.1.9] - 2026-02-14

### ����
- ?? **���ƽӿڲ�������**
  - ���� `patch/eastmoney_patch.py` �޸� efinance ���νӿڱ��
  - ��Ӱ����������Դ����������

## [3.1.8] - 2026-02-14

### ����
- ?? **Webhook ֤��У�鿪��**��Issue #265��
  - ֧�� `WEBHOOK_VERIFY_SSL` �����������ɹر� HTTPS ֤��У����֧����ǩ��֤��
  - Ĭ�ϱ���У�飬�رմ��� MITM ���գ��������ڿ�������ʹ��

## [3.1.7] - 2026-02-14

### �޸�
- ?? �޸����������package import error��

## [3.1.6] - 2026-02-13

### �޸�
- ?? �޸� `news_intel` �� `query_id` ��һ������

## [3.1.5] - 2026-02-13

### ����
- ?? **Markdown תͼƬ֪ͨ**��Issue #289��
  - ֧�� `MARKDOWN_TO_IMAGE_CHANNELS` ���ã��� Telegram����ҵ΢�š��Զ��� Webhook��Discord�����ʼ�����ͼƬ��ʽ����
  - �ʼ�Ϊ������������ǿ�Բ�֧�� HTML �ͻ��˵ļ�����
  - �谲װ `wkhtmltopdf` �� `imgkit`

## [3.1.4] - 2026-02-12

### ����
- ?? **��Ʊ���鷢����ͬ����**��Issue #268��
  - ֧�� `STOCK_GROUP_N` + `EMAIL_GROUP_N` ���ã���ͬ��Ʊ�鱨�淢�͵���Ӧ����
  - ���̸��̷����������õ�����

## [3.1.3] - 2026-02-12

### �޸�
- ?? �޸� Docker ������ʱͨ��ҳ���޸����ñ��� `[Errno 16] Device or resource busy` ������

## [3.1.2] - 2026-02-11

### �޸�
- ?? �޸� Docker һ�������⣬����ؼ����δ�����֪ͨ Bug

## [3.1.1] - 2026-02-11

### ���
- ?? `API_HOST` �� `WEBUI_HOST`��Docker Compose ������ͳһ

## [3.1.0] - 2026-02-11

### ����
- ?? **ETF ֧����ǿ�����淶��**
  - ͳһ������Դ ETF ���봦���߼�
  - ���� `canonical_stock_code()` ͳһ�����ʽ��ȷ������Դ·����ȷ

## [3.0.5] - 2026-02-08

### �޸�
- ?? �޸��ź� emoji �뽨�鲻һ�µ����⣨���Ͻ�����"����/����"δ��ȷӳ�䣩
- ?? �޸� `*ST` ��Ʊ����΢��/Dashboard �� markdown ת������
- ?? �޸� `idx.amount` Ϊ None ʱ���̸��� TypeError
- ?? �޸����� API ���� `report=None` �� ReportStrategy ���Ͳ�һ������
- ?? �޸� Tushare �������ʹ���dict �� UnifiedRealtimeQuote���� API �˵�ָ��

### ����
- ?? ���̸��̱���ע��ṹ�����ݣ��ǵ�ͳ�ơ�ָ�����񡢰��������
- ?? ������� TTL ���棨500 �����ޣ�FIFO ��̭��
- ?? Tushare Token ����ʱ�Զ�ע��ʵʱ�������ȼ�
- ?? ����ժҪ�ضϳ��� 50��200 ��

### �Ż�
- ? ���������ֶ���������Ϊ��� 1 �Σ�������Ч����

## [3.0.4] - 2026-02-07

### ����
- ?? **�ز�����** (PR #269)
  - ����������ʷ������¼�Ļز�ϵͳ��֧�������ʡ�ʤ�ʡ����س���ָ������
  - WebUI ���ɻز���չʾ

## [3.0.3] - 2026-02-07

### �޸�
- ?? �޸��ѻ���λ���ݽ����������� (PR #271)

## [3.0.2] - 2026-02-06

### ����
- ?? �������ʼ����������� (PR #272)
- ?? �����Ʊ֧��Ӣ�Ĺؼ�������

## [3.0.1] - 2026-02-06

### �޸�
- ?? �޸� ETF ʵʱ�����ȡ���г����ݻ��ˡ���ҵ΢����Ϣ�ֿ�����
- ?? CI ���̼�

## [3.0.0] - 2026-02-06

### �Ƴ�
- ??? **�Ƴ��ɰ� WebUI**
  - ɾ������ `http.server.ThreadingHTTPServer` �ľɰ� WebUI��`web/` ����
  - �ɰ� WebUI �Ĺ�������ȫ�� FastAPI��`api/`��+ React ǰ�����
  - `--webui` / `--webui-only` �����в������Ϊ���ã��Զ��ض��� `--serve` / `--serve-only`
  - `WEBUI_ENABLED` / `WEBUI_HOST` / `WEBUI_PORT` �����������ּ��ݣ��Զ�ת���� FastAPI ����
  - `webui.py` ����Ϊ������ڣ�����ʱֱ�ӵ��� FastAPI ���
  - Docker Compose ���Ƴ� `webui` �����壬ͳһʹ�� `server` ����

### ���
- ?? **������ع�**
  - �� `web/services.py` �е��첽�������Ǩ���� `src/services/task_service.py`
  - Bot �������`bot/commands/analyze.py`����Ϊʹ�� `src.services.task_service`
  - Docker �������� `WEBUI_HOST`/`WEBUI_PORT` ����Ϊ `API_HOST`/`API_PORT`�������Լ��ݣ�

## [2.3.0] - 2026-02-01

### ����
- ???? **��ǿ����֧��** (Issue #153)
  - ʵ�ֻ��� Akshare ��������ʷ���ݻ�ȡ (`ak.stock_us_daily()`)
  - ʵ�ֻ��� Yfinance ������ʵʱ�����ȡ�����Ȳ��ԣ�
  - ���ӶԲ�֧������Դ��Tushare/Baostock/Pytdx/Efinance�������ɴ�����˺Ϳ��ٽ���

### �޸�
- ?? �޸� AMD �����ɴ��뱻��ʶ��Ϊ A �ɵ����� (Issue #153)

## [2.2.5] - 2026-02-01

### ����
- ?? **AstrBot ��Ϣ����** (PR #217)
  - ���� AstrBot ֪ͨ������֧�����͵� QQ ��΢��
  - ֧�� HMAC SHA256 ǩ����֤��ȷ��ͨ�Ű�ȫ
  - ͨ�� `ASTRBOT_URL` �� `ASTRBOT_TOKEN` ����

## [2.2.4] - 2026-02-01

### ����
- ?? **����������Դ���ȼ�** (PR #215)
  - ֧��ͨ�������������� `YFINANCE_PRIORITY=0`����̬��������Դ���ȼ�
  - �����޸Ĵ��뼴������ʹ���ض�����Դ���� Yahoo Finance��

## [2.2.3] - 2026-01-31

### �޸�
- ?? ���� requirements.txt������ `lxml_html_clean` �����Խ������������

## [2.2.2] - 2026-01-31

### �޸�
- ?? �޸������������ִ�Сд���� (fixes #211)

## [2.2.1] - 2026-01-31

### �޸�
- ?? **YFinance �������޸�** (PR #210, fixes #209)
  - �޸��°� yfinance ���� MultiIndex �������µ����ݽ�������

## [2.2.0] - 2026-01-31

### ����
- ?? **��Դ���˲�����ǿ**
  - ʵ���˸���׳�����ݻ�ȡ���˻��� (feat: multi-source fallback strategy)
  - �Ż�������Դ����ʱ���Զ��л��߼�

### �޸�
- ?? �޸� analyzer ���к��޷�ͨ���� .env �ļ��� stock_list ���ݵ������ٵĹ�Ʊ

## [2.1.14] - 2026-01-31

### �ĵ�
- ?? ���� README ���Ż� auto-tag ����

## [2.1.13] - 2026-01-31

### �޸�
- ?? **Tushare ���ȼ���ʵʱ����** (Fixed #185)
  - �޸� Tushare ����Դ���ȼ���������
  - �޸� Tushare ʵʱ�����ȡ����

## [2.1.12] - 2026-01-30

### �޸�
- ?? �޸�����������ĳЩ����µ����ִ�Сд����
- ?? �޸����ػ������ô������߼�

## [2.1.11] - 2026-01-30

### �Ż�
- ?? **������Ϣ���Ż�** (PR #192)
  - �Ż����� Stream ģʽ����Ϣ���ʹ���
  - �޸� Stream ��ϢģʽĬ��Ϊ�رգ���ֹ���ô�������ʱ����

## [2.1.10] - 2026-01-30

### �ϲ�
- ?? �ϲ� PR #154 ����

## [2.1.9] - 2026-01-30

### ����
- ?? **΢���ı���Ϣ֧��** (PR #137)
  - ����΢�����͵Ĵ��ı���Ϣ����֧��
  - ���� `WECHAT_MSG_TYPE` ������

## [2.1.8] - 2026-01-30

### �޸�
- ?? ������־�� API �ṩ����ʾ���� (PR #197)

## [2.1.7] - 2026-01-30

### �޸�
- ?? ���ñ��ػ����Ĵ������ã�����������������

## [2.1.6] - 2026-01-29

### ����
- ?? **Pytdx ����Դ (Priority 2)**
  - ����ͨ��������Դ���������ע��
  - ��������Զ��л�
  - ֧��ʵʱ�������ʷ����
- ??? **��Դ��Ʊ���ƽ���**
  - DataFetcherManager ���� `get_stock_name()` ����
  - ���� `batch_get_stock_names()` ������ѯ
  - �Զ��ڶ�����Դ�����
  - Tushare �� Baostock ������Ʊ����/�б�����
- ?? **��ǿ��������**
  - ���� `search_stock_price_fallback()` ��������Դȫ��ʧ��ʱ
  - ��������ά�ȣ��г���������ҵ����
  - ������������� 3 ���ӵ� 5
  - �Ľ����������ʽ��ÿά�� 4 �������

### �Ľ�
- ����������ѯģ������������
- ��ǿ `format_intel_report()` ����ṹ

## [2.1.5] - 2026-01-29

### ����
- ?? ���� Pytdx ����Դ�Ͷ�Դ��Ʊ���ƽ�������

## [2.1.4] - 2026-01-29

### �ĵ�
- ?? ������������Ϣ

## [2.1.3] - 2026-01-28

### �ĵ�
- ?? �ع� README ����
- ?? �����������ķ��� (README_CHT.md)

### �޸�
- ?? �޸� WebUI �޷��������ɴ�������
  - ������߼��ĳ�������ĸ��ת���ɴ�д
  - ֧�� `.` �����루�� `BRK.B`��

## [2.1.2] - 2026-01-27

### �޸�
- ?? �޸����ɷ�������ʧ�ܺͱ���·������ (fixes #166)
- ?? �޸� CR ����ȷ��΢����Ϣ����ֽ�������Ч

## [2.1.1] - 2026-01-26

### ����
- ?? ���� GitHub Actions auto-tag ������
- ?? ���� yfinance ��������Դ������ȱʧ����

### �޸�
- ?? �޸� docker-compose ·�����ĵ�����
- ?? Dockerfile ���� copy src �ļ��� (fixes #145)

## [2.1.0] - 2026-01-25

### ����
- ???? **���ɷ���֧��**
  - ֧�����ɴ���ֱ�����루�� `AAPL`, `TSLA`��
  - ʹ�� YFinance ��Ϊ��������Դ
- ?? **MACD �� RSI ����ָ��**
  - MACD������ȷ�ϡ���������źţ������Ͻ��?�����?������?��
  - RSI���������жϣ�����?��ǿ��?������??��
  - ָ���ź������ۺ�����ϵͳ
- ?? **Discord ����֧��** (PR #124, #125, #144)
  - ֧�� Discord Webhook �� Bot API ���ַ�ʽ
  - ͨ�� `DISCORD_WEBHOOK_URL` �� `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` ����
- ?? **�����������**
  - ����������֧�� `/���� ��Ʊ����` ���������
  - ֧�� Stream ������ģʽ
- ??? **AI �¶Ȳ���������** (PR #142)
  - ֧���Զ��� AI ģ���¶Ȳ���
- ?? **Zeabur ����֧��**
  - ���� Zeabur ����������
  - ֧�� commit hash �� latest ˫��ǩ

### �ع�
- ??? **��Ŀ�ṹ�Ż�**
  - ���Ĵ������� `src/` Ŀ¼����Ŀ¼����ˬ
  - �ĵ����� `docs/` Ŀ¼
  - Docker �������� `docker/` Ŀ¼
  - �޸����� import ·��������������
- ?? **����Դ�ܹ�����**
  - ��������Դ�۶ϻ��ƣ�������Դ����ʧ���Զ��л�
  - ʵʱ���黺���Ż�������Ԥȡ���� API ����
  - ����������ܷ��������ڽӿ��Զ�ֱ��
- ?? Discord �������ع�Ϊƽ̨�������ܹ�

### �޸�
- ?? **�����ȶ�����ǿ**
  - �Զ����������ã��Թ�������ӿ�ǿ��ֱ��
  - �޸� EfinanceFetcher ż���� `ProtocolError`
  - ���ӶԵײ��������Ĳ�������Ի���
- ?? **�ʼ���Ⱦ�Ż�**
  - �޸��ʼ��б�����Ⱦ���� (#134)
  - �Ż��ʼ��Ű棬����������
- ?? **��ҵ΢�������޸�**
  - �޸����̸������Ͳ���������
  - ��ǿ��Ϣ�ָ��߼���֧�ָ�������ʽ
  - ���ӷ������ͼ��������������ʧ
- ?? **CI/CD �޸�**
  - �޸� GitHub Actions ��·�����õĴ���

## [2.0.0] - 2026-01-24

### ����
- ???? **���ɷ���֧��**
  - ֧�����ɴ���ֱ�����루�� `AAPL`, `TSLA`��
  - ʹ�� YFinance ��Ϊ��������Դ
- ?? **�����������** (PR #113)
  - ����������֧�� `/���� ��Ʊ����` ���������
  - ֧�� Stream ������ģʽ
  - ֧��ѡ�񾫼򱨸����������
- ?? **Discord ����֧��** (PR #124)
  - ֧�� Discord Webhook ����
  - ���� Discord ����������������

### �޸�
- ?? �޸� WebUI �� Docker �а� 0.0.0.0 (fixed #118)
- ?? �޸����鳤����֪ͨ����
- ?? �޸� `analysis_delay` δ�������
- ?? ����ʱ config.py ���֪ͨ�������޸��������Զ��������������Ȼ��ʾδ��������

### �Ľ�
- ?? �Ż� Tushare ���ȼ��ж��߼���������װ��
- ?? �޸� Tushare ���ȼ������������� Efinance ֮�������
- ?? ���� TUSHARE_TOKEN ʱ�Զ����� Tushare ����Դ���ȼ�
- ?? ʵ�� 4 ���û����� issue (#112, #128, #38, #119)

## [1.6.0] - 2026-01-19

### ����
- ??? WebUI �������漰 API ֧�֣�PR #72��
  - ȫ�� Web �ܹ����ֲ���ƣ�Server/Router/Handler/Service��
  - ���� API��֧�� `/analysis` (��������), `/tasks` (��ѯ����), `/health` (�������)
  - �������棺֧��ҳ��ֱ��������벢����������ʵʱչʾ����
  - ����ģʽ������ `--webui-only` ģʽ�������� Web ����
  - ����� [#70](https://github.com/ZhuLinsen/daily_stock_analysis/issues/70) �ĺ��������ṩ���������Ľӿڣ�
- ?? GitHub Actions �����������ǿ��[#79](https://github.com/ZhuLinsen/daily_stock_analysis/issues/79)��
  - ֧�ִ� Repository Variables ��ȡ���������ã��� STOCK_LIST, GEMINI_MODEL��
  - ���ֶ� Secrets �����¼���

### �޸�
- ?? �޸���ҵ΢��/���鱨��ض����⣨[#73](https://github.com/ZhuLinsen/daily_stock_analysis/issues/73)��
  - �Ƴ� notification.py �в���Ҫ�ĳ���Ӳ�ض��߼�
  - �����ײ��Զ���Ƭ���ƴ�������Ϣ
- ?? �޸� GitHub Workflow ��������ȱʧ��[#80](https://github.com/ZhuLinsen/daily_stock_analysis/issues/80)��
  - �޸� `CUSTOM_WEBHOOK_BEARER_TOKEN` δ��ȷ���ݵ� Runner ������

## [1.5.0] - 2026-01-17

### ����
- ?? ��������ģʽ��[#55](https://github.com/ZhuLinsen/daily_stock_analysis/issues/55)��
  - ÿ������һֻ��Ʊ�������ͣ����õ�ȫ��������
  - �����в�����`--single-notify`
  - ����������`SINGLE_STOCK_NOTIFY=true`
- ?? �Զ��� Webhook Bearer Token ��֤��[#51](https://github.com/ZhuLinsen/daily_stock_analysis/issues/51)��
  - ֧����Ҫ Token ��֤�� Webhook �˵�
  - ����������`CUSTOM_WEBHOOK_BEARER_TOKEN`

## [1.4.0] - 2026-01-17

### ����
- ?? Pushover ����֧�֣�PR #26��
  - ֧�� iOS/Android ��ƽ̨����
  - ͨ�� `PUSHOVER_USER_KEY` �� `PUSHOVER_API_TOKEN` ����
- ?? �������� API ���ɣ�PR #27��
  - ���������Ż���֧�� AI ժҪ
  - ͨ�� `BOCHA_API_KEYS` ����
- ?? Efinance ����Դ֧�֣�PR #59��
  - ���� efinance ��Ϊ����Դѡ��
- ???? �۹�֧�֣�PR #17��
  - ֧�� 5 λ����� HK ǰ׺���� `hk00700`��`hk1810`��

### �޸�
- ?? ���� Markdown ��Ⱦ�Ż���PR #34��
  - ʹ�ý�����Ƭ�͸�ʽ�����޸���Ⱦ����
- ?? ��Ʊ�б������أ�PR #42 �޸���
  - ����ǰ�Զ����� `STOCK_LIST` ����
- ?? ���� Webhook 20KB ���ƴ���
  - ����Ϣ�Զ��ֿ鷢�ͣ����ⱻ�ض�
- ?? AkShare API ���Ի�����ǿ
  - ����ʧ�ܻ��棬�����ظ�����ʧ�ܽӿ�

### �Ľ�
- ?? README �����Ż�
  - �߼��������� `docs/full-guide.md`


## [1.3.0] - 2026-01-12

### ����
- ?? �Զ��� Webhook ֧��
  - ֧������ POST JSON �� Webhook �˵�
  - �Զ�ʶ�𶤶���Discord��Slack��Bark �ȳ��������ʽ
  - ֧�����ö�� Webhook�����ŷָ���
  - ͨ�� `CUSTOM_WEBHOOK_URLS` ������������

### �޸�
- ?? ��ҵ΢�ų���Ϣ��������
  - �����ѡ�ɹ���ʱ���ݳ��� 4096 �ַ����Ƶ�������ʧ�ܵ�����
  - ���ܰ���Ʊ������ָÿ�����ӷ�ҳ��ǣ��� 1/3, 2/3��
  - ���μ�� 1 �룬���ⴥ��Ƶ������

## [1.2.0] - 2026-01-11

### ����
- ?? ����������֧��
  - ��ҵ΢�� Webhook
  - ���� Webhook��������
  - �ʼ� SMTP��������
  - �Զ�ʶ���������ͣ����ø���

### �Ľ�
- ͳһʹ�� `NOTIFICATION_URL` ���ã����ݾɵ� `WECHAT_WEBHOOK_URL`
- �ʼ�֧�� Markdown ת HTML ��Ⱦ

## [1.1.0] - 2026-01-11

### ����
- ?? OpenAI ���� API ֧��
  - ֧�� DeepSeek��ͨ��ǧ�ʡ�Moonshot������ GLM ��
  - Gemini �� OpenAI ��ʽ��ѡһ
  - �Զ��������Ի���

## [1.0.0] - 2026-01-10

### ����
- ?? AI �����Ǳ��̷���
  - һ�仰���Ľ���
  - ��ȷ����/ֹ��/Ŀ���λ
  - ����嵥��????��
  - �ֲֳֽ��飨�ղ��� vs �ֲ��ߣ�
- ?? ���̸��̹���
  - ��Ҫָ������
  - �ǵ�ͳ��
  - ����ǵ���
  - AI ���ɸ��̱���
- ?? ������Դ֧��
  - AkShare��������Դ����ѣ�
  - Tushare Pro
  - Baostock
  - YFinance
- ?? ������������
  - Tavily API
  - SerpAPI
- ?? ��ҵ΢�Ż���������
- ? ��ʱ�������
- ?? Docker ����֧��
- ?? GitHub Actions ��ɱ�����

### ��������
- Gemini AI ģ�ͣ�gemini-3-flash-preview��
- 429 �����Զ����� + ģ���л�
- �������ʱ�����
- �� API Key ���ؾ���
- SQLite �������ݴ洢

---

[Unreleased]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.31.0...HEAD
[3.31.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.30.0...v3.31.0
[3.30.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.29.0...v3.30.0
[3.29.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.28.0...v3.29.0
[3.28.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.27.0...v3.28.0
[3.27.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.26.1...v3.27.0
[3.26.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.25.0...v3.26.1
[3.25.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.1...v3.25.0
[3.24.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.0...v3.24.1
[3.24.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.23.0...v3.24.0
[3.23.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.22.0...v3.23.0
[3.22.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.1...v3.22.0
[3.21.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.0...v3.21.1
[3.21.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.20.0...v3.21.0
[3.20.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.19.0...v3.20.0
[3.19.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.18.0...v3.19.0
[3.18.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.1...v3.18.0
[3.17.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.0...v3.17.1
[3.17.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.16.0...v3.17.0
[3.16.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.15.0...v3.16.0
[3.15.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.2...v3.15.0
[3.14.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.1...v3.14.2
[3.14.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.0...v3.14.1
[3.14.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.13.0...v3.14.0
[3.13.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.12.0...v3.13.0
[3.12.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.11.0...v3.12.0
[3.11.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.1...v3.11.0
[3.10.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.0...v3.10.1
[3.10.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.9.0...v3.10.0
[3.9.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.8.0...v3.9.0
[3.8.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.7.0...v3.8.0
[3.7.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.6.0...v3.7.0
[3.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.5.0...v3.6.0
[3.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.10...v3.5.0
[3.4.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.9...v3.4.10
[3.4.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.8...v3.4.9
[3.4.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.7...v3.4.8
[3.4.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.0...v3.4.7
[3.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.22...v3.4.0
[3.3.22]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.12...v3.3.22
[3.3.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.11...v3.3.12
[3.2.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.10...v3.2.11
[2.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.5...v2.3.0
[2.2.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.4...v2.2.5
[2.2.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.3...v2.2.4
[2.2.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.14...v2.2.0
[2.1.14]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.13...v2.1.14
[2.1.13]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.12...v2.1.13
[2.1.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.11...v2.1.12
[2.1.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.10...v2.1.11
[2.1.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.9...v2.1.10
[2.1.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.8...v2.1.9
[2.1.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.7...v2.1.8
[2.1.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.6...v2.1.7
[2.1.6]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.5...v2.1.6
[2.1.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.4...v2.1.5
[2.1.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.3...v2.1.4
[2.1.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.2...v2.1.3
[2.1.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.6.0...v2.0.0
[1.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v1.0.0

