use naga::{Arena, Block, Expression, Span, Statement};

pub struct Emitter<'a> {
    indices: Vec<u32>,
    expressions: &'a mut Arena<Expression>,
}

impl<'a> Emitter<'a> {
    pub fn new(exprs: &'a mut Arena<Expression>) -> Emitter<'a> {
        Self {
            indices: Default::default(),
            expressions: exprs,
        }
    }

    fn need_emit(expr: &Expression) -> bool {
        match expr {
            Expression::FunctionArgument(_) => false,
            Expression::GlobalVariable(_) => false,
            Expression::Constant(_) => false,
            Expression::Literal(_) => false,
            Expression::LocalVariable(_) => false,
            Expression::CallResult(_) => false,
            _ => true,
        }
    }

    pub fn emit(self: &mut Self, expr: Expression) -> naga::Handle<Expression> {
        let need_emit_ = Self::need_emit(&expr);
        let handle = self.expressions.append(expr, Span::default());
        if need_emit_ {
            let idx: u32 = (self.expressions.len() - 1)
                .try_into()
                .expect("表达式列表长度过大");
            self.indices.push(idx);
        }
        handle
    }

    pub fn finish(self: &mut Self, block: &mut Block) {
        for idx in &self.indices {
            let range = (*idx)..(idx + 1);
            let range = naga::Range::from_index_range(range, self.expressions);
            block.push(Statement::Emit(range), Span::default());
        }
        self.indices.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use naga::{
        AddressSpace, BinaryOperator, Binding, BuiltIn, EntryPoint, Expression, Function,
        FunctionArgument, GlobalVariable, Literal, MemoryDecorations, Module, ResourceBinding,
        Scalar, ShaderStage, Span, Statement, StorageAccess, Type, TypeInner, VectorSize,
        back::wgsl::{self, WriterFlags},
    };

    #[test]
    fn main() {
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
        let mut emitter = Emitter::new(&mut func.expressions);

        let expr_gid = emitter.emit(Expression::FunctionArgument(0));
        let expr_gid_x = emitter.emit(Expression::AccessIndex {
            base: expr_gid,
            index: 0,
        });
        let expr_data = emitter.emit(Expression::GlobalVariable(global_var_data));
        let expr_data_access_ptr = emitter.emit(Expression::Access {
            base: expr_data,
            index: expr_gid_x,
        });
        let expr_data_access = emitter.emit(Expression::Load {
            pointer: expr_data_access_ptr,
        });
        let expr_constant_2 = emitter.emit(Expression::Literal(Literal::F32(2.)));
        let expr_data_mul_2 = emitter.emit(Expression::Binary {
            op: BinaryOperator::Multiply,
            left: expr_data_access,
            right: expr_constant_2,
        });

        emitter.finish(&mut func.body);
        func.body.push(
            Statement::Store {
                pointer: expr_data_access_ptr,
                value: expr_data_mul_2,
            },
            Span::default(),
        );
        func.body
            .push(Statement::Return { value: None }, Span::default());

        module.entry_points.push(EntryPoint {
            name: "main".to_string(),
            early_depth_test: None,
            function: func,
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
}
