use rand::RngExt;
use wgpu::{
    Backends, BindGroupDescriptor, BindGroupEntry, BindGroupLayoutDescriptor, BindGroupLayoutEntry, BindingType, BufferBindingType, BufferDescriptor, BufferUsages, CommandEncoderDescriptor, ComputePassDescriptor, ComputePipelineDescriptor, PipelineCompilationOptions, PipelineLayoutDescriptor, PollType, ShaderModuleDescriptor, ShaderSource, ShaderStages,
};

mod emitter;
mod gpu;

const DATA_LENGTH: usize = 2971;
const BUFFER_SIZE: usize = DATA_LENGTH * size_of::<f32>();

#[derive(encase::ShaderType)]
struct Uniform {
    data_length: u32,
}

impl Uniform {
    fn as_wgsl_bytes(&self) -> encase::internal::Result<Vec<u8>> {
        let mut buffer = encase::UniformBuffer::new(Vec::new());
        buffer.write(self)?;
        Ok(buffer.into_inner())
    }
}

#[pollster::main]
async fn main() {
    // 创建设备上下文
    let ctx = gpu::WgpuContext::new(Backends::VULKAN).await;

    // 生成数据
    let mut rng = rand::rng();
    let data_host: Vec<f32> = (0..DATA_LENGTH)
        .map(|_| rng.random_range(-2.0f32..2.))
        .collect();
    let buffer = ctx.device.create_buffer(&BufferDescriptor {
        label: None,
        mapped_at_creation: false,
        size: BUFFER_SIZE as u64,
        usage: BufferUsages::STORAGE | BufferUsages::COPY_DST | BufferUsages::COPY_SRC,
    });
    ctx.queue
        .write_buffer(&buffer, 0, &bytemuck::cast_slice(&data_host));

    // uniform buffer 输入
    let uniform = Uniform {
        data_length: DATA_LENGTH as u32,
    };
    let uniform_buffer = ctx.device.create_buffer(&BufferDescriptor {
        label: None,
        mapped_at_creation: false,
        size: size_of::<Uniform>() as u64,
        usage: BufferUsages::UNIFORM | BufferUsages::COPY_DST,
    });
    ctx.queue.write_buffer(
        &uniform_buffer,
        0,
        &uniform
            .as_wgsl_bytes()
            .expect("无法将 uniform 数据转换为字节数组"),
    );

    // 用于将输出传输到 host 的 staging buffer
    let staging_buffer = ctx.device.create_buffer(&BufferDescriptor {
        label: None,
        size: BUFFER_SIZE as u64,
        usage: BufferUsages::COPY_DST | BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });

    // bind group
    let bind_group_layout = ctx
        .device
        .create_bind_group_layout(&BindGroupLayoutDescriptor {
            label: None,
            entries: &[
                BindGroupLayoutEntry {
                    binding: 0,
                    count: None,
                    ty: BindingType::Buffer {
                        ty: BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    visibility: ShaderStages::COMPUTE,
                },
                BindGroupLayoutEntry {
                    binding: 1,
                    count: None,
                    visibility: ShaderStages::COMPUTE,
                    ty: BindingType::Buffer {
                        ty: BufferBindingType::Storage { read_only: false },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                },
            ],
        });
    let bind_group = ctx.device.create_bind_group(&BindGroupDescriptor {
        label: None,
        layout: &bind_group_layout,
        entries: &[
            BindGroupEntry {
                binding: 0,
                resource: uniform_buffer.as_entire_binding(),
            },
            BindGroupEntry {
                binding: 1,
                resource: buffer.as_entire_binding(),
            },
        ],
    });

    // 编译 shader
    let shader = ctx.device.create_shader_module(ShaderModuleDescriptor {
        label: None,
        source: ShaderSource::Wgsl(include_str!("./array_op.wgsl").into()),
    });

    // pipeline
    let pipeline_layout = ctx
        .device
        .create_pipeline_layout(&PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[Some(&bind_group_layout)],
            immediate_size: 0,
        });
    let compute_pipeline = ctx
        .device
        .create_compute_pipeline(&ComputePipelineDescriptor {
            label: None,
            module: &shader,
            layout: Some(&pipeline_layout),
            entry_point: Some("main"),
            cache: None,
            compilation_options: PipelineCompilationOptions::default(),
        });

    // 调用 shader 命令
    let mut encoder = ctx
        .device
        .create_command_encoder(&CommandEncoderDescriptor { label: None });
    {
        let mut compute_pass = encoder.begin_compute_pass(&ComputePassDescriptor {
            label: None,
            timestamp_writes: None,
        });
        compute_pass.set_pipeline(&compute_pipeline);
        compute_pass.set_bind_group(0, &bind_group, &[]);
        compute_pass.dispatch_workgroups(1, 1, 1);
    }
    encoder.copy_buffer_to_buffer(&buffer, 0, &staging_buffer, 0, BUFFER_SIZE as u64);
    ctx.queue.submit(std::iter::once(encoder.finish()));

    // 传回 host 内存
    let buffer_slice = staging_buffer.slice(..);
    buffer_slice.map_async(wgpu::MapMode::Read, |result| {
        if let Err(e) = result {
            eprintln!("映射缓冲区失败: {:?}", e);
        }
    });

    // 等待命令执行完
    ctx.device
        .poll(PollType::wait_indefinitely())
        .inspect_err(|e| println!("device 事件出错：{:#?}", e))
        .unwrap();

    let mapped_data = buffer_slice.get_mapped_range().expect("error");
    let result: &[f32] = bytemuck::cast_slice(&mapped_data);

    // 输出前 10 个元素
    for i in 0..10 {
        println!("#{:0>2}: {:>7.4} ==> {:>7.4}", i, data_host[i], result[i]);
    }
}
