export const STATUSES={queued:'排队中',running:'计算中',completed:'已完成',failed:'失败'};
export const HEALTH={
 unchecked:'未自检',ok:'自检通过',result_corrupted:'结果损坏',source_corrupted:'底稿受损',
 repairing:'修复中',repaired_pending_review:'待重新复核',reapproved:'已重新复核'
};
export const REPAIR_STATUS={queued:'排队中',running:'执行中',succeeded:'已完成',rejected:'已拒绝',failed:'失败'};
export const HEALTH_TONE={
 ok:'tone-ok',reapproved:'tone-ok',unchecked:'tone-muted',
 result_corrupted:'tone-bad',source_corrupted:'tone-bad',
 repairing:'tone-warn',repaired_pending_review:'tone-warn'
};
