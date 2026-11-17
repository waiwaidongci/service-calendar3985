import {HEALTH,HEALTH_TONE} from '../../constants/enums.js';import {esc} from '../../utils/format.js';
export const healthBadge=h=>h?`<span class="health ${esc(HEALTH_TONE[h]||'tone-muted')}">${esc(HEALTH[h]||h)}</span>`:'';
