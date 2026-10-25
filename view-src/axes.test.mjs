import {test} from 'node:test';
import assert from 'node:assert/strict';
import {countChannels, vegaCountAxes} from './axes.js';
test('integer recall counts receive discrete axes through nested bullet layers', () => {
 const input={data:{values:[{correct_answers:6},{correct_answers:9},{correct_answers:10}]},semantic_types:{correct_answers:'Score'},chart_spec:{encodings:{x:{field:'correct_answers'}}}};
 assert.deepEqual(countChannels(input),[{channel:'x',field:'correct_answers'}]);
 const spec={layer:[{encoding:{x:{field:'correct_answers',type:'quantitative'}}}]};
 vegaCountAxes(spec,['correct_answers']);
 assert.deepEqual(spec.layer[0].encoding.x.axis,{format:'d',tickMinStep:1});
});
test('continuous measurements and fractional scores retain their precision',()=>{
 const input={data:{values:[{temperature:6},{temperature:9}]},chart_spec:{encodings:{x:{field:'temperature'}}}};
 assert.deepEqual(countChannels(input),[]);
 input.data.values=[{score:1.5},{score:2.5}];input.chart_spec.encodings.x.field='score';
 assert.deepEqual(countChannels(input),[]);
});

test('out-of counts retain the full denominator in their scale',async()=>{
 const {denominatorDomain}=await import('./axes.js');
 const input={data:{values:[{score:6},{score:9},{score:10}]},chart_spec:{encodings:{y:{field:'score',denominator:12}}}};
 assert.deepEqual(denominatorDomain(input,'y','score'),[0,12]);
 const spec={encoding:{y:{field:'score',type:'quantitative'},x:{field:'day',type:'nominal'}}};
 vegaCountAxes(spec,['score'],{score:[0,12]});
 assert.deepEqual(spec.encoding.y.scale.domain,[0,12]);
 assert.equal(spec.encoding.x.axis.labelAngle,0);
 input.chart_spec.encodings.y.denominator=5;
 assert.equal(denominatorDomain(input,'y','score'),null);
});
