// Counts remain discrete even when a chart engine chooses fractional tick steps.
export function countChannels(input) {
  const rows = input.data?.values || [];
  return Object.entries(input.chart_spec?.encodings || {}).filter(([channel, enc]) => {
    const field = enc.field;
    const hint = `${field} ${input.semantic_types?.[field] || ''}`;
    return ['x', 'y'].includes(channel) && /count|question|answer|score|frequency|integer/i.test(hint)
      && rows.length && rows.every(row => Number.isInteger(row[field]));
  }).map(([channel, enc]) => ({channel, field: enc.field}));
}

export function vegaCountAxes(spec, fields, domains = {}) {
  for (const [key, value] of Object.entries(spec || {})) {
    if (key === 'encoding') {
      for (const enc of Object.values(value)) {
        if (enc && fields.includes(enc.field)) {
          enc.axis = {...enc.axis, format: 'd', tickMinStep: 1};
          if (domains[enc.field]) enc.scale = {...enc.scale,domain:domains[enc.field]};
        }
        if (enc && ['nominal','ordinal'].includes(enc.type)) enc.axis = {...enc.axis,labelAngle:0};
      }
    } else if (Array.isArray(value)) value.forEach(item => {
      if (item && typeof item === 'object') vegaCountAxes(item, fields, domains);
    });
    else if (value && typeof value === 'object') vegaCountAxes(value, fields, domains);
  }
  return spec;
}

export function denominatorDomain(input, channel, field) {
  const declared = input.chart_spec?.encodings?.[channel]?.denominator;
  const labelTotal = /\bout of\s+(\d+)/i.exec(field)?.[1];
  const total = Number(declared ?? labelTotal);
  const rows = input.data?.values || [];
  return Number.isFinite(total) && total > 0 && rows.every(row => Number.isFinite(row[field]) && row[field] >= 0 && row[field] <= total) ? [0,total] : null;
}
