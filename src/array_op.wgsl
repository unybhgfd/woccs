struct Uniforms {
    data_length: u32,
};
@group(0) @binding(0) var<uniform> uniforms: Uniforms;
@group(0) @binding(1) var<storage, read_write> data: array<f32>;

const workgroup_size = 16u;

@compute @workgroup_size(workgroup_size)
fn main(
    @builtin(global_invocation_id) global_id: vec3<u32>, // workgroup_id * num_workgroups + local_id
    @builtin(num_workgroups) num_workgroups: vec3<u32>, // gridDim
    @builtin(local_invocation_id) local_id: vec3<u32>, // threadIdx
    @builtin(workgroup_id) workgroup_id: vec3<u32>, // blockIdx
) {
    let idx = global_id.x;
    let stride = workgroup_size * num_workgroups.x;

    for (var i = idx; i < uniforms.data_length; i += stride) {
        data[i] *= 2;
    }
}
// __global__ void processLargeArray(float* data, int N) {
//     int idx = blockIdx.x * blockDim.x + threadIdx.x;
//     int stride = blockDim.x * gridDim.x;  // 总线程数
//
//     // 每个线程以 stride 为步长遍历
//     for (int i = idx; i < N; i += stride) {
//         data[i] = data[i] * 2.0f;
//     }
// }
