use naga::{
    AddressSpace, BinaryOperator, Binding, Block, BuiltIn, EntryPoint, Expression, Function,
    FunctionArgument, GlobalVariable, Literal, MemoryDecorations, Module, ResourceBinding, Scalar,
    ShaderStage, Span, Statement, StorageAccess, Type, TypeInner, VectorSize,
    back::wgsl::{self, WriterFlags},
    proc::Emitter,
};

#[pollster::main]
async fn main() {
    let mut module = Module::default();

    let type_f32 = module.types.insert(
        Type {
            inner: TypeInner::Scalar(Scalar::F32),
            name: None,
        },
        Span::default(),
    );
    let type_vec3_u32 = module.types.insert(
        Type {
            name: None,
            inner: TypeInner::Vector {
                size: VectorSize::Tri,
                scalar: Scalar::U32,
            },
        },
        Span::default(),
    );
    let type_array_f32 = module.types.insert(
        Type {
            name: None,
            inner: TypeInner::Array {
                size: naga::ArraySize::Dynamic,
                base: type_f32,
                stride: Scalar::F32.width.into(),
            },
        },
        Span::default(),
    );
    let global_var_data = module.global_variables.append(
        GlobalVariable {
            name: None,
            space: AddressSpace::Storage {
                access: StorageAccess::LOAD | StorageAccess::STORE,
            },
            binding: Some(ResourceBinding {
                group: 0,
                binding: 0,
            }),
            ty: type_array_f32,
            init: None,
            memory_decorations: MemoryDecorations::empty(),
        },
        Span::default(),
    );

    let mut func = Function::default();
    func.arguments.push(FunctionArgument {
        name: None,
        ty: type_vec3_u32,
        binding: Some(Binding::BuiltIn(BuiltIn::GlobalInvocationId)),
    });
    let mut func_body = Block::default();
    let mut emitter = Emitter::default();
    emitter.start(&func.expressions);
    let expr_gid = func
        .expressions
        .append(Expression::FunctionArgument(0), Span::default());
    let expr_gid_x = func.expressions.append(
        Expression::AccessIndex {
            base: expr_gid,
            index: 0,
        },
        Span::default(),
    );
    let expr_data = func
        .expressions
        .append(Expression::GlobalVariable(global_var_data), Span::default());
    let expr_data_access_ptr = func.expressions.append(
        Expression::Access {
            base: expr_data,
            index: expr_gid_x,
        },
        Span::default(),
    );
    let expr_data_access = func.expressions.append(
        Expression::Load {
            pointer: expr_data_access_ptr,
        },
        Span::default(),
    );
    let expr_constant_2 = func
        .expressions
        .append(Expression::Literal(Literal::F32(2.)), Span::default());
    let expr_data_mul_2 = func.expressions.append(
        Expression::Binary {
            op: BinaryOperator::Multiply,
            left: expr_data_access,
            right: expr_constant_2,
        },
        Span::default(),
    );

    func_body.push(
        emitter
            .finish(&func.expressions)
            .expect("无法结束 emitter")
            .0,
        Span::default(),
    );
    func_body.push(
        Statement::Store {
            pointer: expr_data_access_ptr,
            value: expr_data_mul_2,
        },
        Span::default(),
    );
    func_body.push(Statement::Return { value: None }, Span::default());
    func.body = func_body;
    println!("{:#?}", func);

    let func_handle = module.functions.append(func, Span::default());
    module.entry_points.push(EntryPoint {
        name: "main".to_string(),
        early_depth_test: None,
        function: module.functions[func_handle].clone(),
        incoming_ray_payload: None,
        mesh_info: None,
        stage: ShaderStage::Compute,
        task_payload: None,
        workgroup_size: [64, 1, 1],
        workgroup_size_overrides: None,
    });

    let info = naga::valid::Validator::new(
        naga::valid::ValidationFlags::all(),
        naga::valid::Capabilities::all(),
    )
    .validate(&module)
    .inspect_err(|e| {
        let e: &naga::valid::ValidationError = e.as_inner();
        println!("验证失败：{:#?}", e);
    })
    .unwrap();

    let wgsl = wgsl::write_string(&module, &info, WriterFlags::empty()).expect("无法生成代码");
    println!("{wgsl}");
}
