// API实体字段约定：来源{id,natural_key,data}、口径{id,version,data}、报告{id,status,snapshot,checksum,result,approved,health,result_version,repair_seq}、
// 结果版本ResultVersion{run_id,version,result_checksum,source_checksum}、修复任务RepairJob{idem_key,status,damage}、事件RunEvent{run_id,seq,action}、
// 复核RunReview{version,state}、计划{next_at,enabled,auto_paused}、交付{result_version,corrected,superseded_by_run_version}。
export const ENTITY_KEYS=['sources','policies','runs','schedules','deliveries','repair_jobs'];
