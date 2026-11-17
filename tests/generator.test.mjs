import test from 'node:test';
import assert from 'node:assert/strict';
import {deviceOverviewModel,renderDeviceGraphic} from '../custom_components/sigen_hybrid/frontend/sigen-hybrid-devices.js';
import {renderDeviceDetail} from '../custom_components/sigen_hybrid/frontend/sigen-hybrid-details.js';

const states={
  generator_power:{state:'2.968',attributes:{unit_of_measurement:'kW'}},
  generator_mode:{state:'Auto',attributes:{start_control_type:'two-wire-start',min_power_percent:0,cooling:false,transfer:{over_voltage_v:253,under_voltage_v:184,over_frequency_hz:55,under_frequency_hz:45},exercise:{enabled:false},load_condition:{enabled:false}}},
  generator_start_soc:{state:'35',attributes:{unit_of_measurement:'%'}},
  generator_stop_soc:{state:'65',attributes:{unit_of_measurement:'%'}},
  generator_charging_stop_soc:{state:'95',attributes:{unit_of_measurement:'%'}},
  generator_max_power:{state:'50',attributes:{unit_of_measurement:'%'}},
  generator_rated_power:{state:'6',attributes:{unit_of_measurement:'kW'}},
  generator_time_of_use:{state:'on',attributes:{periods:[{start:'00:00',duration_minutes:1440,weekdays:[1,2,3,4,5,6,7],start_soc:35,stop_soc:65,max_load_percent:100}]}},
};
const ctx={entities:Object.fromEntries(Object.keys(states).map(key=>[key,`sensor.test_${key}`])),state:key=>states[key],value:key=>states[key]?Number(states[key].state):null};

test('a mapped generator appears as its own device with mode and power',()=>{
  const device=deviceOverviewModel(ctx).find(item=>item.type==='generator');
  assert.ok(device);
  assert.equal(device.route,'generator');
  assert.equal(device.power,2.968);
  assert.equal(device.detail,'Auto');
});

test('no generator tile without generator entities',()=>{
  assert.equal(deviceOverviewModel({}).some(item=>item.type==='generator'),false);
});

test('generator detail shows read-only settings and schedule',()=>{
  const detail=renderDeviceDetail('generator',ctx);
  assert.equal(detail.title,'Generator');
  for(const expected of ['two-wire-start','95 %','50 %','00:00–24:00, Every day','35 % / 65 %','184 V','45 Hz','Change generator settings in the mySigen app'])
    assert.ok(detail.body.includes(expected),expected);
  assert.ok(!detail.body.includes('<script'));
});

test('generator graphic is a decorative vector',()=>{
  const html=renderDeviceGraphic('generator');
  assert.ok(html.includes('data-device-graphic="generator"')&&html.includes('is-vector'));
});
