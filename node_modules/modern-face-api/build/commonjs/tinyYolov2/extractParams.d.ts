import type { ParamMapping } from '../common/types';
import type { TinyYolov2Config } from './config';
import type { TinyYolov2NetParams } from './types';
export declare function extractParams(weights: Float32Array, config: TinyYolov2Config, boxEncodingSize: number, filterSizes: number[]): {
    params: TinyYolov2NetParams;
    paramMappings: ParamMapping[];
};
